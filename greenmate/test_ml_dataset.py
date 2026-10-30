"""B06: temporal leakage, continuity, traceability and transparent labels."""
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import patch

import db
import ml_dataset as dataset
from seed_history import generate_samples


class DatasetTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.database = patch('db.DB_PATH', str(Path(self.directory.name) / 'test.db'))
        self.database.start()
        self.addCleanup(self.database.stop)
        self.config = patch('ml_dataset.CONFIG_PATH', Path(self.directory.name) / 'config.json')
        self.config.start()
        self.addCleanup(self.config.stop)
        db.init_db()
        for row in generate_samples(datetime(2026, 10, 21, tzinfo=timezone.utc)):
            db.add_sample(row)

    def test_temporal_split_trace_and_config_summary_api(self):
        summary = dataset.generate_dataset()
        rows = dataset.build_windows()
        self.assertEqual(summary['train']['count'], 233)
        self.assertEqual(summary['test']['count'], 89)
        self.assertLess(summary['train']['time_range']['end'], summary['test']['time_range']['start'])
        for name in ('train', 'test'):
            self.assertTrue(all(count > 0 for count in summary[name]['class_distribution'].values()))
        original = {row['id']: row for row in dataset.load_samples()}
        train_ids, test_ids = set(), set()
        for row in rows:
            self.assertEqual(len(row['input_sample_ids']), 6)
            self.assertEqual(row['input_timestamps'], [original[key]['timestamp'] for key in row['input_sample_ids']])
            self.assertEqual(set(row['features']), set(dataset.FEATURE_NAMES))
            self.assertEqual(row['label_source'], 'RULE_v1')
            (train_ids if row['split'] == 'train' else test_ids).update(row['input_sample_ids'] + row['future_sample_ids'])
        self.assertFalse(train_ids & test_ids)
        from fastapi.testclient import TestClient
        from main import app
        # Without the context manager, TestClient does not start the unrelated
        # model lifespan. The endpoint itself uses the real temporary SQLite.
        client = TestClient(app, raise_server_exceptions=True)
        try:
            response = client.get('/api/ml/dataset/summary')
            self.assertEqual(response.status_code, 200)
            self.assertEqual(response.json(), summary)
        finally:
            client.close()
        self.assertEqual(dataset.dataset_summary(), summary)

    def test_window_size_four_changes_counts(self):
        summary = dataset.generate_dataset(4, 2)
        self.assertEqual(summary['train']['count'], 235)
        self.assertEqual(summary['test']['count'], 91)
        self.assertEqual(dataset.dataset_summary(), summary)
        with self.assertRaises(ValueError):
            dataset.build_windows(0)

    def test_gaps_duplicates_weather_and_missing_values_are_dropped(self):
        original = dataset.load_samples()
        for mutation in ('gap', 'duplicate', 'weather', 'missing'):
            rows = [dict(row) for row in original]
            if mutation == 'gap':
                rows.pop(10)
            elif mutation == 'duplicate':
                rows[10]['timestamp'] = rows[9]['timestamp']
            elif mutation == 'weather':
                rows[10]['source_type'] = 'REAL_WEATHER'
            else:
                rows[10]['humidity'] = None
            windows, _ = dataset._construct(rows, 6, 2)
            for window in windows:
                ids = window['input_sample_ids'] + window['future_sample_ids']
                if mutation in ('weather', 'missing'):
                    self.assertNotIn(original[10]['id'], ids)
                times = [dataset._moment(next(row['timestamp'] for row in rows if row['id'] == key)) for key in ids]
                self.assertTrue(all(b - a == timedelta(minutes=30) for a, b in zip(times, times[1:])))

    def test_future_changes_labels_but_never_features(self):
        rows = dataset.load_samples()[:8]
        for row in rows:
            row.update(temperature=24, humidity=65, light=10000)
        baseline, _ = dataset._construct(rows, 6, 2)
        self.assertEqual(baseline[0]['label'], 'NORMAL')
        for key, boundary in [('temperature', 32), ('temperature', 10), ('humidity', 35), ('humidity', 85), ('light', 20000), ('light', 800)]:
            changed = [dict(row) for row in rows]
            for row in changed[6:]:
                row[key] = boundary
                row['sim_scenario'] = 'not_a_feature'
            examples, _ = dataset._construct(changed, 6, 2)
            self.assertEqual(examples[0]['features'], baseline[0]['features'])
            self.assertEqual(examples[0]['label'], 'WATCH')
        self.assertEqual(baseline[0]['features']['temp_delta'], 0)
        self.assertEqual(baseline[0]['features']['hum_mean'], 65)


if __name__ == '__main__':
    unittest.main()
