"""S1: anchored snapshots, unchanged model labels, explanation failure archives."""
import io
import json
import sqlite3
from contextlib import closing, redirect_stdout
from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock, patch

import db
import state
import analysis
from analysis import ANALYSIS_QUESTION, run_analysis
from llm import MissingAPIKeyError
from test_agent import AgentCase


class AnalysisTests(AgentCase):
    def seed(self, anchor=None, count=6):
        self.anchor = anchor or datetime(2026, 10, 21, 12, tzinfo=timezone.utc)
        for index in range(count):
            db.add_sample({'timestamp': (self.anchor - timedelta(minutes=30*(5-index))).isoformat(),
                           'temperature': 29.5 + (index % 2) * .1,
                           'humidity': 65 + (index % 2) * .2, 'light': 12000,
                           'source_type': 'SIMULATED', 'sim_scenario': 's1_stable'})
        db.save_state_to_db({'timestamp': self.anchor.isoformat(), 'temperature': 29.6,
                             'humidity': 65.2, 'light': 12000, 'source_type': 'SIMULATED'})
        state.load_state()

    async def test_fixed_question_anchored_history_real_saved_model_and_recall(self):
        self.seed()
        # Later rows must not leak into past-anchor history or model input.
        db.add_sample({'timestamp': (self.anchor+timedelta(microseconds=1)).isoformat(), 'temperature': 99,
                       'humidity': 2, 'light': 1, 'source_type': 'SIMULATED'})
        before = db.get_samples_at(self.anchor, 3)
        with patch('analysis.explain_analysis', AsyncMock(return_value='仅解释提供的模拟证据。')) as explain, patch('sklearn.linear_model.LogisticRegression.fit', side_effect=AssertionError('no retraining')):
            response = await self.client.post('/api/analyze', json={'analysis_time': self.anchor.isoformat()})
        self.assertEqual(response.status_code, 200)
        run = response.json()
        self.assertEqual(run['question'], '分析当前番茄生长环境状态以及接下来值得关注的变化，并说明判断依据。')
        self.assertEqual(run['question'], ANALYSIS_QUESTION)
        self.assertEqual(run['history_window']['end'], run['analysis_time'])
        self.assertEqual(run['history_window']['items'], before)
        self.assertEqual(run['prediction']['model_version'], 'attention_v1')
        self.assertEqual(run['prediction']['status'], 'ok')
        self.assertEqual(run['prediction']['window_end'], self.anchor.isoformat())
        self.assertEqual(run['prediction']['target_start'], self.anchor.isoformat())
        self.assertEqual(run['prediction']['target_end'], (self.anchor+timedelta(hours=1)).isoformat())
        self.assertEqual(run['judgment']['generated_by'], 'PROGRAM')
        self.assertEqual(run['judgment']['recent_trend']['metrics']['temperature']['direction'], 'stable')
        self.assertEqual(explain.await_args.args[0], ANALYSIS_QUESTION)
        self.assertEqual(db.get_samples_at(self.anchor, 3), before)
        # Change B02 state, then retrieve the frozen run after a new connection.
        state.update_state({'temperature': 10})
        recalled = (await self.client.get('/api/analyze/'+run['run_id'])).json()
        self.assertEqual(recalled, run)
        self.assertEqual(recalled['state']['data']['temperature'], 29.6)

    async def test_watch_never_overridden_by_stable_trend(self):
        self.seed()
        watch = {'status': 'ok', 'prediction': 'WATCH', 'probability': .93, 'model_version': 'attention_v1', 'evidence_type': 'MODEL_OUTPUT'}
        with patch('analysis.predict_window', return_value=watch), patch('analysis.explain_analysis', AsyncMock(return_value='稳定趋势与WATCH预测是不同证据。')):
            run = await run_analysis(self.anchor)
        self.assertEqual(run['judgment']['recent_trend']['metrics']['temperature']['direction'], 'stable')
        self.assertEqual(run['judgment']['predicted_attention']['prediction'], 'WATCH')
        self.assertEqual(run['prediction']['probability'], .93)

    async def test_insufficient_history_and_llm_failure_still_saved(self):
        self.seed(count=5)
        with patch('analysis.explain_analysis', AsyncMock(side_effect=MissingAPIKeyError)):
            run = await run_analysis(self.anchor)
        self.assertEqual(run['evidence_status']['recent_history'], 'unavailable')
        self.assertEqual(run['evidence_status']['prediction'], 'unavailable')
        self.assertEqual(run['answer'], '')
        self.assertEqual(run['judgment']['explanation_status'], 'unavailable')
        self.assertIn('已保存', run['judgment']['llm_error']['message'])
        self.assertEqual(db.get_analysis_run(run['run_id']), run)

    async def test_duplicate_gap_and_future_current_state_not_used(self):
        self.seed()
        with closing(sqlite3.connect(db._database_path())) as connection, connection:
            connection.execute('UPDATE environment_samples SET timestamp=? WHERE id=3', ((self.anchor-timedelta(minutes=75)).isoformat(),))
        # Current snapshot after a past anchor must not masquerade as as-of data.
        state.update_state({'temperature': 40})
        with patch('analysis.explain_analysis', AsyncMock(return_value='证据不齐。')):
            run = await run_analysis(self.anchor)
        self.assertEqual(run['evidence_status']['current_state'], 'unavailable')
        self.assertEqual(run['judgment']['current_state'], None)
        self.assertEqual(run['evidence_status']['recent_history'], 'unavailable')

    async def test_list_latest_five_and_validation(self):
        self.seed()
        with patch('analysis.explain_analysis', AsyncMock(return_value='档案解释。')):
            for _ in range(6):
                await run_analysis(self.anchor)
            self.assertEqual((await self.client.post('/api/analyze')).status_code, 200)
        items = (await self.client.get('/api/analyze')).json()['items']
        self.assertEqual(len(items), 5)
        self.assertEqual(len({item['run_id'] for item in items}), 5)
        self.assertEqual((await self.client.get('/api/analyze/missing')).status_code, 404)
        for payload in ({'question': '改变固定问题'}, {'analysis_time': '2026-01-01'}, {'analysis_time': '2099-01-01T00:00:00+00:00'}, {'location': '   '}):
            response = await self.client.post('/api/analyze', json=payload)
            self.assertIn(response.status_code, (400, 422))

    async def test_s1_preparation_is_stable_idempotent_and_preserves_old_rows(self):
        from prepare_s1 import prepare_s1
        old = {'timestamp': '2026-01-01T00:00:00+00:00', 'temperature': 24,
               'humidity': 65, 'light': 12000, 'source_type': 'SIMULATED', 'sim_scenario': 'seed_demo'}
        db.add_sample(old)
        with patch('prepare_s1.PREPARATION_PATH'):
            first = prepare_s1()
            second = prepare_s1()
        with closing(sqlite3.connect(db._database_path())) as connection:
            rows = connection.execute('SELECT temperature,humidity,source_type,sim_scenario FROM environment_samples ORDER BY id').fetchall()
        self.assertEqual(len(rows), 7)
        self.assertEqual(rows[0], (24.0, 65.0, 'SIMULATED', 'seed_demo'))
        self.assertTrue(all(29 <= row[0] <= 30 for row in rows[1:]))
        self.assertLessEqual(max(row[1] for row in rows[1:])-min(row[1] for row in rows[1:]), 2)
        self.assertEqual(second['mode'], 'reused_existing_stable_segment')

    async def test_s1_can_complete_partial_calm_grid_without_overwrite(self):
        from prepare_s1 import prepare_s1
        self.seed(datetime.now(timezone.utc)-timedelta(minutes=2), count=5)
        original = db.get_samples_at(self.anchor, 3)
        with patch('prepare_s1.PREPARATION_PATH'):
            prepared = prepare_s1()
        latest = db.get_samples_at(datetime.fromisoformat(prepared['analysis_time']), 3)
        self.assertEqual(len(latest), 6)
        self.assertEqual(prepared['mode'], 'completed_existing_stable_segment')
        self.assertEqual(latest[:5], original)
