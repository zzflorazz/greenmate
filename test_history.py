import math
import sqlite3
import unittest
from contextlib import closing
from datetime import datetime, timedelta, timezone
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch
from zoneinfo import ZoneInfo

import db
import seed_history
import tools


class HistoryTests(unittest.TestCase):
    def setUp(self):
        self.temp_dir = TemporaryDirectory()
        self.path_patch = patch('db.DB_PATH', str(Path(self.temp_dir.name) / 'history.db'))
        self.path_patch.start()
        db.init_db()

    def tearDown(self):
        self.path_patch.stop()
        self.temp_dir.cleanup()

    def test_seed_exact_count_interval_sources_and_idempotence(self):
        before = db.get_state_from_db()
        self.assertEqual(seed_history.seed_history(), 336)
        first = db.get_samples(168)
        self.assertEqual(len(first), 336)
        self.assertTrue(all(row['source_type'] == 'SIMULATED' and row['sim_scenario'] == 'seed_demo' for row in first))
        moments = [datetime.fromisoformat(row['timestamp']) for row in first]
        self.assertEqual(moments, sorted(moments))
        self.assertTrue(all((b - a).total_seconds() == 1800 for a, b in zip(moments, moments[1:])))
        self.assertEqual(seed_history.seed_history(datetime.now(timezone.utc) + timedelta(days=1)), 0)
        self.assertEqual(db.get_samples(168), first)
        self.assertEqual(db.get_state_from_db(), before)
        night = [row['light'] for row in first if datetime.fromisoformat(row['timestamp']).astimezone(ZoneInfo('Asia/Shanghai')).hour < 5]
        day = [row['light'] for row in first if 11 <= datetime.fromisoformat(row['timestamp']).astimezone(ZoneInfo('Asia/Shanghai')).hour < 14]
        self.assertTrue(all(value == 0 for value in night))
        self.assertGreater(sum(day) / len(day), 10000)
        self.assertGreater(len({row['temperature'] for row in first}), 100)

    def test_add_and_query_chronological_window(self):
        now = datetime.now(timezone.utc)
        for hours in (1, 26, 2, -1):
            db.add_sample({'timestamp': (now - timedelta(hours=hours)).isoformat(), 'temperature': 24, 'humidity': 65, 'light': 12000, 'source_type': 'MANUAL'})
        samples = db.get_samples()
        self.assertEqual(len(samples), 2)
        self.assertLess(samples[0]['timestamp'], samples[1]['timestamp'])
        self.assertTrue(all(row['sim_scenario'] is None for row in samples))

    def test_tool_hours_validation_and_empty_history_is_ok(self):
        for hours in (-1, 0, 169, '24', None, True, float('nan'), float('inf')):
            self.assertEqual(tools.get_environment_history(hours)['status'], 'error')
        result = tools.get_environment_history()
        self.assertEqual(result['status'], 'ok')
        self.assertEqual(result['data']['items'], [])
        self.assertIsNone(result['error'])


if __name__ == '__main__':
    unittest.main()
