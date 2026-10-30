"""Disabled sources are archived, never called or fed into judgment."""
from copy import deepcopy
from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock, Mock, patch

import db
import rag
import tools
import analysis
from scenarios import apply_scenario
from test_agent import AgentCase
from test_s3_weather import forecast


class DisabledEvidenceTests(AgentCase):
    async def test_flags_archive_disabled_sources_without_changing_judgment(self):
        anchor = datetime.now(timezone.utc)-timedelta(seconds=2)
        apply_scenario('S4_conflict',anchor)
        records = {}
        knowledge_item = rag.simple_search('番茄高温')[0]
        async def explain(question, judgment):
            return ('历史和天气有分歧，conclusion_level=conflicting。' if judgment['conflicts'] else '核心描述有依据。') + ('番茄tomato_heat_01仅作参考。' if judgment['knowledge']['status']=='ok' else '本次知识未启用。')
        for weather_enabled, knowledge_enabled in ((False,False),(True,False),(False,True),(True,True)):
            with self.subTest(weather=weather_enabled, knowledge=knowledge_enabled):
                weather=Mock(return_value=forecast(anchor,temperatures=(20,17,14)))
                knowledge=Mock(return_value=tools.tool_result('ok','LOCAL_KNOWLEDGE',{'items':[knowledge_item]}))
                with patch('analysis.get_weather_forecast',weather), patch.dict(tools.TOOL_FUNCTIONS,{'search_plant_knowledge':knowledge}), patch('analysis.explain_analysis',AsyncMock(side_effect=explain)), patch('analysis.assess_conflicts',wraps=analysis.assess_conflicts) as assess:
                    response=await self.client.post('/api/analyze',json={'analysis_time':anchor.isoformat(),'include_weather':weather_enabled,'include_knowledge':knowledge_enabled})
                self.assertEqual(response.status_code,200)
                run=response.json();records[(weather_enabled,knowledge_enabled)]=run
                entries={e['source_type']:e for e in run['judgment']['evidence_records']}
                self.assertEqual(len(entries),5)
                for source,enabled,tool in [('KNOWLEDGE',knowledge_enabled,knowledge),('WEATHER_FORECAST',weather_enabled,weather)]:
                    evidence=entries[source]
                    self.assertEqual(evidence['status'],'ok' if enabled else 'unavailable')
                    if enabled:
                        tool.assert_called_once()
                    else:
                        tool.assert_not_called()
                        self.assertEqual(evidence['time'],run['analysis_time'])
                        self.assertIsNone(evidence['result'])
                        self.assertIn('include_knowledge=false' if source=='KNOWLEDGE' else 'include_weather=false',evidence['error'])
                        self.assertNotIn(source,[t['source_type'] for t in run['tool_trace']])
                if not knowledge_enabled:
                    self.assertEqual(entries['KNOWLEDGE'],{'source_type':'KNOWLEDGE','source':'LOCAL_KNOWLEDGE','time':run['analysis_time'],'status':'unavailable','result':None,'error':'本次分析未启用知识库（include_knowledge=false）'})
                # Existing conflict/level logic receives exactly the same adopted
                # evidence it did before this archive-only correction.
                adopted=assess.call_args.args[0]
                self.assertTrue(all(e['status']=='ok' for e in adopted))
                self.assertEqual(len(adopted),3+weather_enabled+knowledge_enabled)
                self.assertEqual(db.get_analysis_run(run['run_id']),run)
                self.assertEqual(run['judgment']['explanation_status'],'ok')
        baseline=records[(False,False)]
        for run in records.values():
            self.assertEqual(run['prediction'],baseline['prediction'])
            self.assertEqual(run['history_window'],baseline['history_window'])
        off,on=records[(False,False)],records[(True,True)]
        compared=(await self.client.get('/api/analyze/compare',params={'run_a':off['run_id'],'run_b':on['run_id']})).json()
        self.assertEqual(compared['evidence_records']['run_a'],off['judgment']['evidence_records'])
        self.assertEqual(compared['evidence_records']['run_b'],on['judgment']['evidence_records'])
        self.assertTrue(all(e['status']=='unavailable' for e in compared['evidence_records']['run_a'] if e['source_type'] in ('KNOWLEDGE','WEATHER_FORECAST')))
