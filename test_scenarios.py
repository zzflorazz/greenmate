"""S2 controlled-history contrast, idempotence and immutable analysis assets."""
import hashlib
import json
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import AsyncMock, patch

import db
from main import app
from scenarios import apply_scenario
from test_agent import AgentCase


class ScenarioTests(AgentCase):
    async def test_repeat_same_scene_and_switch_keep_six_points(self):
        anchor = datetime.now(timezone.utc)-timedelta(seconds=2)
        first = apply_scenario('S1_stable', anchor)
        original = db.get_samples_at(anchor, 3)
        repeated = apply_scenario('S1_stable')
        self.assertEqual(repeated['analysis_time'], first['analysis_time'])
        self.assertEqual(repeated['samples_written'], 0)
        self.assertEqual(db.get_samples_at(anchor, 3), original)
        second = apply_scenario('S2_ramp', anchor)
        points = db.get_samples_at(anchor, 3)
        self.assertEqual(len(points), 6)
        self.assertEqual([row['temperature'] for row in points], [25,26,27,28,29,30])
        self.assertTrue(all(row['source_type']=='SIMULATED' and row['sim_scenario']=='S2_ramp' for row in points))
        self.assertEqual(second['current_state'], first['current_state'])
        self.assertEqual(apply_scenario('S2_ramp',anchor)['samples_written'], 0)

    async def test_same_analysis_produces_real_process_and_probability_delta(self):
        baseline = json.loads(Path(__file__).with_name('verification').joinpath('s2_baseline_hashes.json').read_text())
        # S3 explicitly extends analysis.py; preserve the historical S2 baseline,
        # while keeping prompts and saved model immutable across both stages.
        baseline.pop('analysis.py')
        before = {name:hashlib.sha256(Path(name).read_bytes()).hexdigest() for name in baseline}
        self.assertEqual(before, baseline)
        async def explain(question, judgment):
            metric = judgment['recent_trend']['metrics']['temperature']
            return f"固定问题的测试解释。\n\n温度{metric['first']}到{metric['last']}，{metric['direction']}。"
        with patch('analysis.explain_analysis', AsyncMock(side_effect=explain)):
            a = (await self.client.post('/api/analyze/scenario',json={'name':'S1_stable'})).json()
            b = (await self.client.post('/api/analyze/scenario',json={'name':'S2_ramp','analysis_time':a['run']['analysis_time']})).json()
        ra, rb = a['run'], b['run']
        self.assertEqual(ra['question'], rb['question'])
        self.assertEqual(ra['analysis_time'],rb['analysis_time'])
        self.assertEqual(ra['judgment']['current_state'],rb['judgment']['current_state'])
        self.assertEqual(ra['judgment']['recent_trend']['metrics']['temperature']['direction'],'stable')
        self.assertEqual(rb['judgment']['recent_trend']['metrics']['temperature']['direction'],'rising')
        self.assertEqual(rb['judgment']['recent_trend']['metrics']['temperature']['delta'],5)
        self.assertEqual(ra['prediction']['model_version'],'attention_v1')
        self.assertEqual(rb['prediction']['model_version'],'attention_v1')
        self.assertNotEqual(ra['prediction']['probability'],rb['prediction']['probability'])
        compared = (await self.client.get('/api/analyze/compare',params={'run_a':a['run_id'],'run_b':b['run_id']})).json()
        self.assertTrue(compared['fixed_question_match'])
        self.assertTrue(compared['same_analysis_time'])
        self.assertEqual(len(compared['rows']),6)
        changed = {row['field'] for row in compared['structured_delta']['changed']}
        unchanged = {row['field'] for row in compared['structured_delta']['unchanged']}
        self.assertIn('recent_trend.temperature.direction',changed)
        self.assertIn('prediction.probability',changed)
        self.assertIn('current.temperature',unchanged)
        self.assertIn('evidence_status',unchanged)
        self.assertEqual((await self.client.get('/api/analyze/'+ra['run_id'])).json(),ra)
        self.assertEqual({name:hashlib.sha256(Path(name).read_bytes()).hexdigest() for name in baseline},before)
        same = (await self.client.get('/api/analyze/compare',params={'run_a':a['run_id'],'run_b':a['run_id']})).json()
        self.assertEqual(same['structured_delta']['changed'],[])
        self.assertTrue(any('窗口温度序列' in note for note in same['notes']))

    async def test_preserves_unmanaged_rows_and_rejects_bad_names(self):
        anchor = datetime.now(timezone.utc)-timedelta(seconds=1)
        sample={'timestamp':anchor.isoformat(),'temperature':24,'humidity':65,'light':12000,'source_type':'SIMULATED','sim_scenario':'seed_demo'}
        db.add_sample(sample)
        before=db.get_samples_at(anchor,3)
        with self.assertRaisesRegex(ValueError,'保留原数据'):
            apply_scenario('S1_stable',anchor)
        self.assertEqual(db.get_samples_at(anchor,3),before)
        for payload in ({'name':'unknown'},{'name':'S1_stable','question':'改问题'},{'name':'S1_stable','analysis_time':'bad'}):
            response=await self.client.post('/api/scenarios/apply',json=payload)
            self.assertIn(response.status_code,(400,422))
        self.assertEqual((await self.client.get('/api/analyze/compare',params={'run_a':'missing','run_b':'missing'})).status_code,404)
