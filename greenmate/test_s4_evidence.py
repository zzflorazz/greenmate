"""S4 program contracts. Offline forecasts are explicitly fixtures, not live weather."""
import ast
from contextlib import closing
from copy import deepcopy
from datetime import datetime, timedelta, timezone
import hashlib
import json
from pathlib import Path
import sqlite3
from unittest.mock import AsyncMock, Mock, patch

import analysis
import db
import rag
import tools
from analysis import ANALYSIS_QUESTION, run_analysis
from evidence import FORBIDDEN, explanation_issue
from scenarios import apply_scenario
from test_agent import AgentCase
from test_s3_weather import forecast

SAFE = '内部历史升温，外部预报降温，空间和时间范围不同，存在分歧。模型原始标签保留。番茄知识tomato_heat_01仅作条件性管理参考。缺内部后续实测和生育期；conclusion_level=conflicting。'


class S4EvidenceTests(AgentCase):
    def prepare(self):
        self.anchor = datetime.now(timezone.utc) - timedelta(seconds=2)
        apply_scenario('S4_conflict', self.anchor)

    def weather(self):
        return patch('analysis.get_weather_forecast', return_value=forecast(self.anchor, temperatures=(20, 17, 14)))

    def knowledge(self):
        # Real registered function + real B04 code, with encoder failure fixture
        # to exercise its documented keyword fallback without network/model load.
        return patch('rag.get_embedding', side_effect=RuntimeError('offline encoder fixture'))

    async def test_real_registry_invocation_five_sources_conflicts_and_archive(self):
        self.prepare()
        original_model = analysis.predict_window(db.get_samples_at(self.anchor, 3))
        with self.weather(), self.knowledge(), patch.dict(tools.TOOL_FUNCTIONS, {'search_plant_knowledge': tools.search_plant_knowledge}), patch('analysis.explain_analysis', AsyncMock(return_value=SAFE)):
            with patch.dict(tools.TOOL_FUNCTIONS, {'search_plant_knowledge': Mock(wraps=tools.search_plant_knowledge)}):
                run = await run_analysis(self.anchor, include_weather=True, include_knowledge=True)
                called = tools.TOOL_FUNCTIONS['search_plant_knowledge']
                called.assert_called_once()
                query = called.call_args.kwargs['query']
        self.assertIn(ANALYSIS_QUESTION, query)
        self.assertIn('32.0', query)
        self.assertIn('24000', query)
        self.assertEqual(run['question'], ANALYSIS_QUESTION)
        j = run['judgment']
        self.assertEqual({e['source_type'] for e in j['evidence_records']}, {'CURRENT_STATE','HISTORY','MODEL_OUTPUT','WEATHER_FORECAST','KNOWLEDGE'})
        for record in j['evidence_by_type']:
            self.assertTrue({'source_type','source','time','status','result','error'} <= record.keys())
            self.assertIsNotNone(record['source'])
            self.assertIsNotNone(datetime.fromisoformat(record['time']).tzinfo)
        self.assertEqual(j['conclusion_level'], 'conflicting')
        self.assertTrue(any(c['between'] == ['HISTORY','WEATHER_FORECAST'] for c in j['conflicts']))
        self.assertEqual(j['knowledge']['citation'][0]['id'], 'tomato_heat_01')
        self.assertEqual(run['prediction'], {**original_model, 'analysis_time': self.anchor.isoformat()})
        self.assertTrue(all(t['adopted'] and t['status']=='ok' for t in run['tool_trace']))
        self.assertEqual(db.get_analysis_run(run['run_id']), run)
        self.assertEqual(run['answer'], SAFE)
        self.assertFalse(FORBIDDEN.search(run['answer']))

    async def test_disabled_knowledge_not_called_other_sources_unchanged(self):
        self.prepare()
        with self.weather(), self.knowledge(), patch('analysis.explain_analysis', AsyncMock(return_value=SAFE)):
            enabled = await run_analysis(self.anchor, include_weather=True, include_knowledge=True)
        answer = '内部历史升温与外部预报降温有分歧；知识关闭，未取得知识。缺后续内部实测。conclusion_level=conflicting。'
        with self.weather(), patch.dict(tools.TOOL_FUNCTIONS, {'search_plant_knowledge': Mock(side_effect=AssertionError('must not call'))}), patch('analysis.explain_analysis', AsyncMock(return_value=answer)):
            disabled = await run_analysis(self.anchor, include_weather=True, include_knowledge=False)
            tools.TOOL_FUNCTIONS['search_plant_knowledge'].assert_not_called()
        self.assertEqual(disabled['judgment']['knowledge']['status'], 'unavailable')
        self.assertEqual(disabled['evidence_status']['knowledge'], 'unavailable')
        self.assertNotIn('search_plant_knowledge', [t['tool'] for t in disabled['tool_trace']])
        self.assertEqual(len(disabled['judgment']['evidence_records']), 5)
        self.assertEqual(sum(e['status']=='ok' for e in disabled['judgment']['evidence_records']), 4)
        for key in ('prediction','history_window'):
            self.assertEqual(enabled[key], disabled[key])
        self.assertEqual(enabled['state']['data'], disabled['state']['data'])

    async def test_ok_empty_bad_citation_and_irrelevant_not_adopted(self):
        self.prepare()
        item = rag.simple_search('番茄高温')[0]
        invalid = deepcopy(item); invalid['citation']['snippet'] = '伪造片段'
        irrelevant = rag.simple_search('绿萝')[0]
        for items in ([], [invalid], [irrelevant]):
            with self.weather(), patch('tools.vector_search', return_value=items), patch('analysis.explain_analysis', AsyncMock(return_value='历史与天气有分歧；缺可采用知识。conclusion_level=conflicting。')):
                run = await run_analysis(self.anchor, include_weather=True, include_knowledge=True)
            trace = next(t for t in run['tool_trace'] if t['tool']=='search_plant_knowledge')
            self.assertEqual(trace['status'], 'ok')
            self.assertFalse(trace['adopted'])
            self.assertIn('未采用', trace['adopt_reason'])
            self.assertNotIn('KNOWLEDGE', [e['source_type'] for e in run['judgment']['evidence_records']])

    async def test_weather_tool_ok_but_past_points_not_adopted(self):
        self.prepare()
        with patch('analysis.get_weather_forecast', return_value=forecast(self.anchor, (-3,-2,-1))), patch('analysis.explain_analysis', AsyncMock(return_value='预报时间不适用，缺可采用的外部天气。')):
            run = await run_analysis(self.anchor, include_weather=True)
        trace = next(t for t in run['tool_trace'] if t['tool']=='get_weather_forecast')
        self.assertEqual(trace['status'], 'ok')
        self.assertFalse(trace['adopted'])
        self.assertEqual(run['judgment']['weather_evidence']['status'], 'error')

    async def test_normal_never_changed_and_no_conflict_fabricated_for_same_direction(self):
        self.prepare()
        normal = {'status':'ok','prediction':'NORMAL','probability':.12,'model_version':'attention_v1','evidence_type':'MODEL_OUTPUT'}
        with self.weather(), self.knowledge(), patch('analysis.predict_window', return_value=deepcopy(normal)), patch('analysis.explain_analysis', AsyncMock(return_value=SAFE)):
            run = await run_analysis(self.anchor, include_weather=True, include_knowledge=True)
        self.assertEqual(run['prediction']['prediction'], 'NORMAL')
        self.assertEqual(run['prediction']['probability'], .12)
        self.assertTrue(any(c['type']=='attention_divergence' for c in run['judgment']['conflicts']))
        with patch('analysis.get_weather_forecast', return_value=forecast(self.anchor, temperatures=(14,17,20))), patch('analysis.explain_analysis', AsyncMock(return_value='内部历史与外部预报均升温，范围仍不同。')):
            same = await run_analysis(self.anchor, include_weather=True)
        self.assertFalse(same['judgment']['conflicts'])
        self.assertEqual(same['judgment']['conclusion_level'], 'supported')

    async def test_output_guard_blocks_absolutes_and_unreported_conflict(self):
        self.prepare()
        for answer in ('综合来看一定会恶化。', '必然恶化。', '综合来看无需关注。'):
            with self.weather(), patch('analysis.explain_analysis', AsyncMock(return_value=answer)) as explain:
                run = await run_analysis(self.anchor, include_weather=True)
            self.assertEqual(explain.await_count, 2)
            self.assertEqual(run['answer'], '')
            self.assertEqual(run['judgment']['conclusion_level'], 'conflicting')
            self.assertEqual(run['judgment']['llm_error']['type'], 'EXPLANATION_REJECTED')
            self.assertEqual(db.get_analysis_run(run['run_id']), run)
        self.assertIsNotNone(explanation_issue('根据检索到的番茄知识，建议关注。', {'evidence_records': [], 'conclusion_level':'insufficient'}))

    async def test_tool_failure_does_not_drop_other_evidence_or_archive(self):
        self.prepare()
        with self.weather(), patch.dict(tools.TOOL_FUNCTIONS, {'search_plant_knowledge': lambda **kw: (_ for _ in ()).throw(RuntimeError('fixture'))}), patch('analysis.explain_analysis', AsyncMock(return_value='历史升温与外部降温有分歧，知识工具不可用。conclusion_level=conflicting。')):
            run = await run_analysis(self.anchor, include_weather=True, include_knowledge=True)
        self.assertEqual(run['judgment']['knowledge']['status'], 'error')
        self.assertEqual(len(run['judgment']['evidence_records']), 4)
        self.assertEqual(run['judgment']['conclusion_level'], 'conflicting')
        self.assertEqual(db.get_analysis_run(run['run_id']),run)

    async def test_api_flags_and_s4_scenario_idempotence(self):
        self.prepare()
        self.assertEqual(apply_scenario('S4_conflict', self.anchor)['samples_written'], 0)
        self.assertEqual([x['light'] for x in db.get_samples_at(self.anchor,3)], [18000,19200,20400,21600,22800,24000])
        with self.weather(), self.knowledge(), patch('analysis.explain_analysis', AsyncMock(return_value=SAFE)):
            for route, body in [('/api/analyze', {}),('/api/analyze/scenario', {'name':'S4_conflict'})]:
                result = await self.client.post(route,json={**body,'analysis_time':self.anchor.isoformat(),'include_weather':True,'include_knowledge':True})
                self.assertEqual(result.status_code,200)
                data=result.json();run=data.get('run',data)
                self.assertEqual(run['judgment']['conclusion_level'],'conflicting')
                self.assertEqual((await self.client.post(route,json={**body,'include_knowledge':'false'})).status_code,422)

    async def test_source_contract_citations_and_protected_files(self):
        records=rag.load_knowledge()
        self.assertEqual(len({r['id'] for r in records}),len(records))
        for name in [r['name'] for r in records]:
            item=rag.simple_search(name)[0]
            self.assertTrue({'id','name','snippet'}<=item['citation'].keys())
        tree=ast.parse(Path('analysis.py').read_text())
        self.assertFalse(any(isinstance(n, ast.ImportFrom) and n.module=='rag' for n in ast.walk(tree)))
        baseline=json.loads(Path('verification/s3_baseline_hashes.json').read_text())
        actual = {p:hashlib.sha256(Path(p).read_bytes()).hexdigest() for p in baseline}
        tool_source = Path('tools.py').read_text().replace('            },\n            headers={"User-Agent": "GreenMate/1.0"},\n            timeout=5, allow_redirects=False,', '            }, timeout=5, allow_redirects=False,')
        actual['tools.py'] = hashlib.sha256(tool_source.encode()).hexdigest()
        self.assertEqual(actual,baseline)

    async def test_missing_knowledge_time_and_insufficient_core_evidence(self):
        self.prepare()
        item = rag.simple_search('番茄高温')[0]
        bad = tools.tool_result('ok','LOCAL_KNOWLEDGE',{'items':[item]});bad['time']=None
        with patch.dict(tools.TOOL_FUNCTIONS, {'search_plant_knowledge': Mock(return_value=bad)}), patch('analysis.explain_analysis', AsyncMock(return_value='知识身份不全，未采用。')):
            run=await run_analysis(self.anchor,include_knowledge=True)
        self.assertEqual(run['judgment']['knowledge']['status'],'error')
        self.assertFalse(run['tool_trace'][-1]['adopted'])
        with patch('analysis._history',return_value={'status':'unavailable','start':self.anchor.isoformat(),'end':self.anchor.isoformat(),'interval':'(start, end]','hours':3,'items':[],'count':0,'source':'SQLITE','error':'fixture'}), patch('analysis.explain_analysis',AsyncMock(return_value='历史与模型不足。')):
            insufficient=await run_analysis(self.anchor)
        self.assertEqual(insufficient['judgment']['conclusion_level'],'insufficient')

    async def test_legacy_database_migration_retains_existing_run(self):
        legacy = Path(self.temp_dir.name)/'legacy.db'
        with closing(sqlite3.connect(legacy)) as connection, connection:
            connection.execute('CREATE TABLE analysis_runs (run_id TEXT PRIMARY KEY, analysis_time TEXT, location TEXT, question TEXT, state_json TEXT, history_window_json TEXT, prediction_json TEXT, judgment_json TEXT, answer TEXT, evidence_status_json TEXT, created_at TEXT)')
            connection.execute('INSERT INTO analysis_runs VALUES (?,?,?,?,?,?,?,?,?,?,?)',('old','time','北京','old-question','{}','{}','{}','{}','old-answer','{}','time'))
        with patch('db.DB_PATH',str(legacy)):
            db.init_db();db.init_db()
            row=db.get_analysis_run('old')
        self.assertEqual(row['answer'],'old-answer')
        self.assertEqual(row['tool_trace'],[])

    async def test_explanation_timezones_must_not_be_silently_dropped(self):
        judgment={'evidence_records': [], 'conclusion_level':'supported'}
        self.assertIsNotNone(explanation_issue('分析时间2026-10-25T08:05:18（北京时间）。',judgment))
        self.assertIsNone(explanation_issue('分析时间2026-10-25T08:05:18+00:00，UTC。',judgment))
        self.assertIsNone(explanation_issue('分析时间2026-10-25T08:05:18.123456+00:00，UTC。',judgment))
