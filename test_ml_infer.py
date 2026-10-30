"""Persist/load contracts, newest-window inference and read-only API/tools."""
import hashlib
import io
import json
import shutil
import sqlite3
import subprocess
import sys
import tempfile
import unittest
from contextlib import closing, redirect_stdout
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import patch

import joblib
import httpx2
import os
import requests
import ml_dataset as dataset
import ml_infer
import ml_train
import db
from seed_history import generate_samples


class InferenceTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.fixture = tempfile.TemporaryDirectory()
        root = Path(cls.fixture.name)
        cls.database = root / 'fixture.db'
        cls.models = root / 'models'
        with patch('db.DB_PATH', str(cls.database)), patch('ml_dataset.CONFIG_PATH', root / 'config.json'), patch('ml_train.MODELS_DIR', cls.models), patch('ml_train.METRICS_PATH', root / 'metrics.json'), redirect_stdout(io.StringIO()):
            db.init_db()
            for row in generate_samples(datetime(2026, 10, 21, 9, tzinfo=timezone.utc)):
                db.add_sample(row)
            dataset.generate_dataset()
            ml_train.train_and_evaluate()

    @classmethod
    def tearDownClass(cls):
        cls.fixture.cleanup()

    def setUp(self):
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        root = Path(directory.name)
        self.database_path = root / 'db.sqlite'
        shutil.copy2(self.database, self.database_path)
        self.models_path = root / 'models'
        shutil.copytree(self.models, self.models_path)
        for target, value in [('db.DB_PATH', str(self.database_path)), ('ml_infer.MODELS_DIR', self.models_path)]:
            patcher = patch(target, value)
            patcher.start()
            self.addCleanup(patcher.stop)

    def test_loaded_probability_matches_training_feature_scaler_and_no_writes(self):
        before = self.database_path.read_bytes()
        payload = ml_infer.load_model()
        features = dataset._features(dataset.load_samples()[-6:])
        matrix = [[features[name] for name in dataset.FEATURE_NAMES]]
        expected = float(payload['model'].predict_proba(payload['scaler'].transform(matrix))[0, 1])
        with patch('sklearn.linear_model.LogisticRegression.fit', side_effect=AssertionError('no training')), patch('sklearn.preprocessing.StandardScaler.fit', side_effect=AssertionError('no scaler fitting')):
            result = ml_infer.predict_latest()
        self.assertEqual(result['status'], 'ok')
        self.assertEqual(result['model_version'], 'attention_v1')
        self.assertEqual(result['evidence_type'], 'MODEL_OUTPUT')
        self.assertAlmostEqual(result['probability'], expected)
        self.assertEqual(before, self.database_path.read_bytes())

    def test_manifest_reordered_features_rejected(self):
        path = self.models_path / 'attention_v1_manifest.json'
        manifest = json.loads(path.read_text())
        manifest['feature_names'][0:2] = reversed(manifest['feature_names'][0:2])
        path.write_text(json.dumps(manifest))
        with self.assertRaisesRegex(ValueError, '顺序不一致'):
            ml_infer.load_model()
        self.assertEqual(ml_infer.predict_latest()['status'], 'unavailable')

    def test_artifact_requires_fitted_scaler(self):
        path = self.models_path / 'attention_v1.joblib'
        payload = joblib.load(path)
        del payload['scaler']
        joblib.dump(payload, path)
        manifest_path = self.models_path / 'attention_v1_manifest.json'
        manifest = json.loads(manifest_path.read_text())
        manifest['artifact_sha256'] = hashlib.sha256(path.read_bytes()).hexdigest()
        manifest_path.write_text(json.dumps(manifest))
        with self.assertRaisesRegex(ValueError, '缺少'):
            ml_infer.load_model()

    def test_latest_gap_does_not_fall_back(self):
        with closing(sqlite3.connect(self.database_path)) as connection, connection:
            connection.execute('DELETE FROM environment_samples WHERE id=335')
        result = ml_infer.predict_latest()
        self.assertEqual(result['status'], 'unavailable')
        self.assertIn('不连续', result['error'])

    def test_insufficient_points_missing_model_and_bad_latest_value(self):
        with closing(sqlite3.connect(self.database_path)) as connection, connection:
            connection.execute('UPDATE environment_samples SET humidity=NULL WHERE id=336')
        self.assertIn('无效数值', ml_infer.predict_latest()['error'])
        with closing(sqlite3.connect(self.database_path)) as connection, connection:
            connection.execute('DELETE FROM environment_samples WHERE id < 332')
        self.assertIn('不足6个', ml_infer.predict_latest()['error'])
        (self.models_path / 'attention_v1.joblib').unlink()
        self.assertEqual(ml_infer.predict_latest()['status'], 'unavailable')

    def test_api_and_tool_envelope(self):
        from fastapi.testclient import TestClient
        from main import app
        import tools
        client = TestClient(app)
        try:
            response = client.get('/api/ml/predict')
            self.assertEqual(response.status_code, 200)
            self.assertEqual(response.json()['status'], 'ok')
            result = tools.predict_next_attention()
            self.assertEqual(result['data'], response.json())
            self.assertEqual(result['source'], 'MODEL_OUTPUT')
            self.assertIsNone(result['error'])
            with closing(sqlite3.connect(self.database_path)) as connection, connection:
                connection.execute('DELETE FROM environment_samples')
            result = tools.predict_next_attention()
            self.assertEqual(result['status'], 'unavailable')
            self.assertEqual(result['data']['model_version'], 'attention_v1')
            self.assertEqual(result['data']['evidence_type'], 'MODEL_OUTPUT')
            self.assertTrue(result['error'])
        finally:
            client.close()

    def test_fresh_python_process_loads_without_training_import(self):
        code = '''import json, sys
from pathlib import Path
import db, ml_infer
db.DB_PATH = sys.argv[1]
ml_infer.MODELS_DIR = Path(sys.argv[2])
assert 'ml_train' not in sys.modules
print(json.dumps(ml_infer.predict_latest()))
assert 'ml_train' not in sys.modules
'''
        output = subprocess.check_output([sys.executable, '-c', code, str(self.database_path), str(self.models_path)], text=True)
        self.assertEqual(json.loads(output)['status'], 'ok')

    def test_native_agent_executes_prediction_and_keeps_evidence_separate(self):
        from fastapi.testclient import TestClient
        from openai import AsyncOpenAI
        from main import app
        import test_agent
        sent = []
        def transport(request):
            payload = json.loads(request.content)
            sent.append(payload)
            self.assertIn('MODEL_OUTPUT', payload['messages'][0]['content'])
            self.assertIn('不确定性', payload['messages'][0]['content'])
            if len(sent) == 1:
                return test_agent.completion(calls=[
                    test_agent.tool_call('predict_next_attention', '{}', 'predict_1'),
                    test_agent.tool_call('get_weather_forecast', '{"location":"北京"}', 'weather_1'),
                    test_agent.tool_call('search_plant_knowledge', '{"query":"绿萝浇水"}', 'knowledge_1'),
                ])
            results = [json.loads(message['content']) for message in payload['messages'] if message['role'] == 'tool']
            self.assertEqual(results[0]['data']['evidence_type'], 'MODEL_OUTPUT')
            self.assertEqual(results[1]['status'], 'unavailable')
            self.assertEqual(results[2]['source'], 'LOCAL_KNOWLEDGE')
            return test_agent.completion('模型预测（MODEL_OUTPUT）：attention_v1基于SIMULATED规则标签，存在不确定性。天气证据：不可用。养护知识：绿萝需检查盆土；预测不能替代天气和知识。')
        def factory(**kwargs):
            return AsyncOpenAI(**kwargs, http_client=httpx2.AsyncClient(transport=httpx2.MockTransport(transport)))
        client = TestClient(app)
        before = self.database_path.read_bytes()
        try:
            with patch.dict(os.environ, {'GREENMATE_API_KEY': 'offline-test'}), patch('agent.AsyncOpenAI', side_effect=factory), patch('tools.requests.get', side_effect=requests.Timeout('injected')), patch('tools.vector_search', return_value=[{'name': '绿萝', 'tips': '检查盆土'}]), redirect_stdout(io.StringIO()) as logs:
                response = client.post('/api/agent', json={'question': '预测接下来一小时要不要关注，并结合天气和养护知识说明'})
            self.assertEqual(response.status_code, 200)
            result = response.json()
            self.assertEqual([call['tool'] for call in result['tool_calls']], ['predict_next_attention', 'get_weather_forecast', 'search_plant_knowledge'])
            self.assertEqual(result['tool_calls'][0]['status'], 'ok')
            self.assertEqual(result['tool_calls'][0]['result']['data']['model_version'], 'attention_v1')
            self.assertEqual(result['tool_calls'][0]['result']['data']['evidence_type'], 'MODEL_OUTPUT')
            self.assertIn('天气证据', result['answer'])
            self.assertIn('养护知识', result['answer'])
            self.assertIn('[agent.tool]', logs.getvalue())
            self.assertEqual(before, self.database_path.read_bytes())
            evidence_path = os.environ.get('GREENMATE_PREDICTION_EVIDENCE')
            if evidence_path:
                evidence = {'mode': 'real_python_tools_and_saved_model_with_mocked_llm_weather_knowledge_transport',
                            'environment_samples_unchanged': before == self.database_path.read_bytes(),
                            'result': result, 'observable_logs': logs.getvalue()}
                target = Path(evidence_path)
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_text(json.dumps(evidence, ensure_ascii=False, indent=2) + '\n')
        finally:
            client.close()


if __name__ == '__main__':
    unittest.main()
