"""Configuration boundary, uniform failures and the single-page data routes."""
import io
from contextlib import redirect_stdout
from unittest.mock import AsyncMock, patch

import httpx2
import settings
import state
from agent import AgentRunError
from main import app
from test_agent import AgentCase


class ProductTests(AgentCase):
    async def test_uniform_validation_http_and_unexpected_errors(self):
        response = await self.client.post('/api/ask', json={'question': ' '})
        self.assertEqual(response.status_code, 422)
        self.assertEqual(set(response.json()['error']), {'code', 'message', 'hint'})
        self.assertEqual((await self.client.get('/not-a-route')).json()['error']['code'], 'HTTP_404')
        previous = state.get_state()
        with patch('main.fetch_weather', return_value=None):
            response = await self.client.post('/api/set-source', json={'source': 'REAL_WEATHER'})
        self.assertEqual(response.status_code, 502)
        self.assertIn('现有状态未改变', response.json()['error']['message'])
        self.assertEqual(state.get_state(), previous)
        async with httpx2.AsyncClient(transport=httpx2.ASGITransport(app=app, raise_app_exceptions=False), base_url='http://test') as client:
            with patch('main.get_state', side_effect=RuntimeError('secret failure details')), redirect_stdout(io.StringIO()):
                response = await client.get('/api/state')
        self.assertEqual(response.status_code, 500)
        self.assertNotIn('secret failure', response.text)
        self.assertEqual(response.json()['error']['code'], 'INTERNAL_ERROR')

    async def test_llm_failure_envelope_retains_tool_evidence(self):
        trace = [{'sequence': 1, 'tool': 'get_current_environment', 'arguments': {}, 'status': 'ok', 'result': {'status': 'ok', 'data': {}}, 'elapsed_ms': 1}]
        with patch('main.run_agent', AsyncMock(side_effect=AgentRunError('模型总结失败。', 502, trace, 2))):
            response = await self.client.post('/api/agent', json={'question': '看看环境'})
        result = response.json()
        self.assertEqual(result['tool_calls'], trace)
        self.assertIn('llm_error', result)
        self.assertEqual(result['error']['code'], 'LLM_UNAVAILABLE')

    async def test_knowledge_search_history_and_prediction_unavailable(self):
        with patch('main.vector_search', return_value=[{'name': '绿萝'}]) as search:
            response = await self.client.get('/api/knowledge/search', params={'query': '绿萝'})
        self.assertEqual(response.json()['items'], [{'name': '绿萝'}])
        search.assert_called_once_with('绿萝')
        self.assertEqual((await self.client.get('/api/knowledge/search', params={'query': '   '})).status_code, 400)
        self.assertEqual((await self.client.get('/api/environment/history')).json()['count'], 0)
        unavailable = {'status': 'unavailable', 'error': '采样不连续。', 'model_version': 'attention_v1', 'evidence_type': 'MODEL_OUTPUT'}
        with patch('main.predict_latest', return_value=unavailable):
            response = await self.client.get('/api/ml/predict')
        self.assertEqual(response.status_code, 503)
        self.assertEqual(response.json()['error']['code'], 'PREDICTION_UNAVAILABLE')
        self.assertEqual(response.json()['model_version'], 'attention_v1')

    async def test_configuration_validation_and_missing_key_notice(self):
        import os
        with patch.dict(os.environ, {'GREENMATE_API_KEY': '', 'GREENMATE_BASE_URL': 'https://api.deepseek.com', 'GREENMATE_MODEL': 'deepseek-chat', 'WEATHER_LAT': '39.9', 'WEATHER_LON': '116.4', 'DB_PATH': 'demo.db'}):
            config = settings.get_settings()
            self.assertEqual(config.db_path, 'demo.db')
            with redirect_stdout(io.StringIO()) as output:
                config.report_startup()
            self.assertIn('联网问答不可用', output.getvalue())
            with patch.dict(os.environ, {'WEATHER_LAT': '999'}):
                with self.assertRaisesRegex(ValueError, '有效经纬度'):
                    settings.get_settings().validate()
            with patch.dict(os.environ, {'GREENMATE_API_KEY': 'never-print-this-key'}):
                self.assertNotIn('never-print-this-key', repr(settings.get_settings()))
