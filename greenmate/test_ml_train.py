"""Check train-only fitting, metric meaning, error reporting and metrics API."""
import io
import json
import tempfile
import unittest
from contextlib import redirect_stdout
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import patch

import numpy as np
from sklearn.linear_model import LogisticRegression
from sklearn.preprocessing import StandardScaler

import db
import ml_dataset as dataset
import ml_train
from seed_history import generate_samples


class TrainingTests(unittest.TestCase):
    def setUp(self):
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        root = Path(directory.name)
        for target, value in [('db.DB_PATH', str(root / 'db.sqlite')),
                              ('ml_train.MODELS_DIR', root / 'models'),
                              ('ml_dataset.CONFIG_PATH', root / 'config.json'),
                              ('ml_train.METRICS_PATH', root / 'metrics.json')]:
            patcher = patch(target, value)
            patcher.start()
            self.addCleanup(patcher.stop)
        db.init_db()
        for row in generate_samples(datetime(2026, 10, 21, 9, tzinfo=timezone.utc)):
            db.add_sample(row)
        dataset.generate_dataset()

    def test_train_only_fit_and_metrics_roundtrip(self):
        fits, transforms, model_fits = [], [], []
        class AuditedScaler(StandardScaler):
            def fit(self, X, y=None, **kwargs):
                fits.append(np.array(X, copy=True))
                return super().fit(X, y, **kwargs)
            def transform(self, X, **kwargs):
                transforms.append(np.array(X, copy=True))
                return super().transform(X, **kwargs)
        class AuditedLogistic(LogisticRegression):
            def fit(self, X, y, **kwargs):
                model_fits.append((np.array(X, copy=True), np.array(y, copy=True)))
                return super().fit(X, y, **kwargs)
        windows = dataset.build_windows()
        train_rows = [row for row in windows if row['split'] == 'train']
        test_rows = [row for row in windows if row['split'] == 'test']
        train_x = ml_train._matrix(train_rows)
        test_x = ml_train._matrix(test_rows)
        with patch('ml_train.StandardScaler', AuditedScaler), patch('ml_train.LogisticRegression', AuditedLogistic), patch('ml_train._save_model'), redirect_stdout(io.StringIO()) as output:
            report = ml_train.train_and_evaluate()
        self.assertTrue(output.getvalue().startswith('训练集/测试集类别分布：'))
        self.assertEqual(len(fits), 1)
        np.testing.assert_array_equal(fits[0], train_x)
        self.assertEqual(len(model_fits), 1)
        self.assertEqual(model_fits[0][0].shape, (233, 8))
        np.testing.assert_array_equal(model_fits[0][1], ml_train._targets(train_rows))
        np.testing.assert_allclose(model_fits[0][0].mean(axis=0), 0, atol=1e-12)
        np.testing.assert_array_equal(transforms[-1], test_x)
        np.testing.assert_allclose(report['training_audit']['scaler_mean'], train_x.mean(axis=0))
        self.assertEqual(report['features'], dataset.FEATURE_NAMES)
        self.assertEqual(json.loads(ml_train.METRICS_PATH.read_text()), report)
        self.assertEqual(report['majority_class'], 'NORMAL')
        for name in ('majority', 'logistic_regression'):
            for split, size in [('train', 233), ('test', 89)]:
                score = report['baselines'][name][split]
                matrix = score['confusion_matrix']
                self.assertEqual(sum(matrix.values()), size)
                self.assertAlmostEqual(score['accuracy'], (matrix['TN'] + matrix['TP']) / size)
                self.assertAlmostEqual(score['recall'], matrix['TP'] / (matrix['TP'] + matrix['FN']))
        for error in report['error_samples']:
            self.assertNotEqual(error['true_label'], error['predicted_label'])
            self.assertEqual(set(error['features']), set(dataset.FEATURE_NAMES))
            self.assertIn('事后回查', error['explanation'])
            self.assertTrue(0 <= error['predicted_probability_watch'] <= 1)
        from fastapi.testclient import TestClient
        import main
        with patch('main.METRICS_PATH', ml_train.METRICS_PATH):
            client = TestClient(main.app)
            try:
                self.assertEqual(client.get('/api/ml/metrics').json(), report)
                ml_train.METRICS_PATH.unlink()
                self.assertEqual(client.get('/api/ml/metrics').status_code, 404)
            finally:
                client.close()

    def test_perfect_predictions_choose_closest_boundary(self):
        original = dataset.load_samples()
        test_rows = [row for row in dataset.build_windows() if row['split'] == 'test'][:2]
        targets = ml_train._targets(test_rows)
        probabilities = np.array([0.9 if targets[0] else 0.1, 0.55 if targets[1] else 0.45])
        analyzed = ml_train._analyze_errors(test_rows, targets, probabilities, original)
        self.assertEqual(len(analyzed), 1)
        self.assertEqual(analyzed[0]['sample_id'], test_rows[1]['sample_id'])
        self.assertEqual(analyzed[0]['type'], 'BOUNDARY')
        self.assertIn('没有错分', analyzed[0]['explanation'])

    def test_watch_is_positive_and_zero_division_is_explicit(self):
        score = ml_train._scores(np.array([0, 1, 1, 0]), np.array([0, 1, 0, 1]))
        self.assertEqual(score['confusion_matrix'], {'TN': 1, 'FP': 1, 'FN': 1, 'TP': 1})
        self.assertEqual(score['precision'], 0.5)
        self.assertEqual(score['recall'], 0.5)
        self.assertEqual(ml_train._scores([0, 1], [0, 0])['precision'], 0)


if __name__ == '__main__':
    unittest.main()
