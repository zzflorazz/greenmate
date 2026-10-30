"""S3: one weather tool, precise future-time filtering, immutable internal evidence."""
import hashlib
import json
from copy import deepcopy
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import AsyncMock, patch

import requests
import db
from analysis import _weather, run_analysis
from llm import MissingAPIKeyError
from scenarios import apply_scenario
from test_agent import AgentCase


def forecast(anchor, offsets=(0, 1, 6), temperatures=(30, 31, 33)):
    return {'status': 'ok', 'source': 'OPEN_METEO', 'time': datetime.now(timezone.utc).isoformat(),
            'data': {'location': '北京', 'timezone': 'UTC', 'units': {'temperature': '°C', 'humidity': '%'},
                     'items': [{'timestamp': (anchor + timedelta(hours=h)).isoformat(), 'temperature': t,
                                'humidity': 65} for h, t in zip(offsets, temperatures)]}, 'error': None}


class S3WeatherTests(AgentCase):
    def prepare(self):
        self.anchor = datetime.now(timezone.utc) - timedelta(seconds=2)
        apply_scenario('S1_stable', self.anchor)

    async def test_identical_internal_evidence_future_weather_archived_and_recalled(self):
        self.prepare()
        before = db.get_samples_at(self.anchor, 3)
        with patch('analysis.get_weather_forecast', return_value=forecast(self.anchor)) as weather, patch('analysis.explain_analysis', AsyncMock(return_value='测试解释，非真实LLM。')) as explain:
            a = await run_analysis(self.anchor)
            weather.assert_not_called()
            b = await run_analysis(self.anchor, include_weather=True)
            weather.assert_called_once_with('北京')
        for key in ('history_window', 'prediction', 'question'):
            self.assertEqual(a[key], b[key])
        self.assertEqual(a['judgment']['weather_expectation'], 'unknown')
        self.assertEqual(a['judgment']['attention_adjustment'], 'none')
        self.assertEqual(a['evidence_status']['weather'], 'unavailable')
        self.assertEqual(a['state']['data'], b['state']['data'])
        j = b['judgment']
        self.assertEqual(j['weather_expectation'], 'warming')
        self.assertEqual(j['attention_adjustment'], 'raise')
        self.assertIn('33°C', j['adjustment_reason'])
        self.assertIn('外部', j['adjustment_reason'])
        w = j['weather_evidence']
        self.assertEqual(w['source_type'], 'WEATHER_FORECAST')
        self.assertEqual(w['provider'], 'OPEN_METEO')
        self.assertEqual(w['retrieved_at'], w['time'])
        self.assertEqual(w['forecast_time']['start'], self.anchor.isoformat())
        self.assertTrue(all(datetime.fromisoformat(p['timestamp']) >= self.anchor for p in w['result']['items']))
        self.assertEqual(explain.await_args.args[1]['weather_evidence'], w)
        self.assertEqual(db.get_samples_at(self.anchor, 3), before)
        self.assertEqual((await self.client.get('/api/analyze/'+b['run_id'])).json(), b)
        self.assertEqual(b['prediction']['model_version'], 'attention_v1')

    async def test_precise_time_filter_and_all_past_error(self):
        self.prepare()
        payload = forecast(self.anchor, (-1, 0, 1), (99, 30, 31))
        payload['data']['items'][0]['timestamp'] = (self.anchor-timedelta(microseconds=1)).isoformat()
        # Same instant with another timezone must still be accepted.
        payload['data']['items'][1]['timestamp'] = self.anchor.astimezone(timezone(timedelta(hours=8))).isoformat()
        with patch('analysis.get_weather_forecast', return_value=payload):
            result = _weather(self.anchor, '北京', True)
        self.assertEqual(result['status'], 'ok')
        self.assertEqual(result['excluded_past_count'], 1)
        self.assertEqual([p['temperature'] for p in result['result']['items']], [30, 31])
        with patch('analysis.get_weather_forecast', return_value=forecast(self.anchor, (-3,-2,-1))), patch('analysis.explain_analysis', AsyncMock(return_value='天气早于分析锚点，不能采用。')):
            run = await run_analysis(self.anchor, include_weather=True)
        self.assertEqual(run['evidence_status']['weather'], 'error')
        self.assertIn('预报时间早于分析时刻', run['judgment']['weather_evidence']['error'])
        self.assertEqual(run['judgment']['weather_evidence']['result']['items'], [])
        self.assertEqual(run['judgment']['weather_expectation'], 'unknown')
        self.assertEqual(run['judgment']['attention_adjustment'], 'none')
        self.assertEqual(run['prediction']['status'], 'ok')

    async def test_real_tool_timeout_and_llm_failure_keep_other_evidence(self):
        self.prepare()
        with patch('tools.requests.get', side_effect=requests.Timeout('simulated timeout')) as request, patch('analysis.explain_analysis', AsyncMock(side_effect=MissingAPIKeyError)):
            response = await self.client.post('/api/analyze/scenario', json={'name':'S1_stable', 'analysis_time':self.anchor.isoformat(), 'include_weather':True})
        self.assertEqual(response.status_code, 200)
        run = response.json()['run']
        self.assertEqual(request.call_args.kwargs['timeout'], 5)
        self.assertEqual(run['evidence_status']['weather'], 'unavailable')
        self.assertIn('超时', run['judgment']['weather_evidence']['error'])
        self.assertTrue(all(run['evidence_status'][k]=='ok' for k in ('current_state','recent_history','prediction')))
        self.assertEqual(db.get_analysis_run(run['run_id']), run)
        self.assertFalse(run['answer'])

    async def test_both_api_routes_pass_flag_and_reject_nonboolean(self):
        self.prepare()
        with patch('analysis.get_weather_forecast', return_value=forecast(self.anchor)) as weather, patch('analysis.explain_analysis', AsyncMock(return_value='测试解释。')):
            for route, body in [('/api/analyze', {}), ('/api/analyze/scenario', {'name':'S1_stable'})]:
                response = await self.client.post(route, json={**body,'analysis_time':self.anchor.isoformat(),'include_weather':True})
                self.assertEqual(response.status_code, 200)
                data = response.json(); run = data.get('run',data)
                self.assertEqual(run['evidence_status']['weather'], 'ok')
                self.assertEqual((await self.client.post(route,json={**body,'include_weather':'yes'})).status_code,422)
            self.assertEqual(weather.call_count, 2)

    async def test_cooling_and_flat_do_not_override_watch_or_invent_rain(self):
        self.prepare()
        watch={'status':'ok','prediction':'WATCH','probability':.93,'model_version':'attention_v1','evidence_type':'MODEL_OUTPUT'}
        for temps, expectation, adjustment in [((20,18,15),'cooling','raise'),((20,20.1,20.2),'unknown','none')]:
            with patch('analysis.get_weather_forecast', return_value=forecast(self.anchor,temperatures=temps)), patch('analysis.predict_window',return_value=deepcopy(watch)), patch('analysis.explain_analysis',AsyncMock(return_value='测试解释。')):
                run=await run_analysis(self.anchor,include_weather=True)
            self.assertEqual(run['judgment']['weather_expectation'],expectation)
            self.assertEqual(run['judgment']['attention_adjustment'],adjustment)
            self.assertEqual(run['prediction']['prediction'],'WATCH')
            self.assertEqual(run['prediction']['probability'],.93)

    async def test_missing_timezone_rejected_and_protected_assets_unchanged(self):
        self.prepare()
        data=forecast(self.anchor);data['data']['items'][0]['timestamp']='2026-10-21T14:00:00'
        with patch('analysis.get_weather_forecast',return_value=data):
            self.assertEqual(_weather(self.anchor,'北京',True)['status'],'error')
        baseline=json.loads(Path('verification/s3_baseline_hashes.json').read_text())
        actual = {p:hashlib.sha256(Path(p).read_bytes()).hexdigest() for p in baseline}
        tool_source = Path('tools.py').read_text().replace('            },\n            headers={"User-Agent": "GreenMate/1.0"},\n            timeout=5, allow_redirects=False,', '            }, timeout=5, allow_redirects=False,')
        actual['tools.py'] = hashlib.sha256(tool_source.encode()).hexdigest()
        self.assertEqual(actual,baseline)
