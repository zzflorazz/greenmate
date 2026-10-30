"""Five consecutive real /api/agent requests, using synthetic DB data only."""
import asyncio
import json
from contextlib import redirect_stdout
from datetime import datetime, timezone
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

import httpx2
import db
from main import app
from seed_history import seed_history


async def verify():
    directory = Path(__file__).with_name('verification')
    directory.mkdir(exist_ok=True)
    question = '预测接下来一小时要不要关注，并结合北京天气和绿萝养护知识说明。请区分模型预测、天气和知识证据并说明不确定性。'
    report = {'mode': 'five_sequential_real_llm_api_agent_requests_via_asgi',
              'data_scope': 'fresh_temporary_SIMULATED_seed_demo_only; public_Beijing_coordinates',
              'started_at': datetime.now(timezone.utc).isoformat(), 'question': question, 'runs': []}
    path = directory / 'llm_retry_live_5.json'
    with TemporaryDirectory(prefix='greenmate-retry-public-demo-') as temporary:
        with patch('db.DB_PATH', str(Path(temporary) / 'synthetic.db')), patch('tools.WEATHER_LAT', '39.9'), patch('tools.WEATHER_LON', '116.4'):
            with (directory / 'llm_retry_live_5.log').open('w', encoding='utf-8') as log:
                with redirect_stdout(log):
                    seed_history()
                    before = db.get_samples(168)
                    async with app.router.lifespan_context(app):
                        async with httpx2.AsyncClient(transport=httpx2.ASGITransport(app=app), base_url='http://greenmate.local') as client:
                            for index in range(1, 6):
                                print(f'[verification.run] run={index} start', file=log, flush=True)
                                response = await client.post('/api/agent', json={'question': question})
                                result = response.json()
                                normal = response.status_code == 200 and not result.get('llm_error') and bool(result.get('answer')) and '已达到5轮上限' not in result['answer']
                                coverage = {call['tool'] for call in result.get('tool_calls', [])}
                                report['runs'].append({'run': index, 'http_status': response.status_code, 'normal_answer': normal,
                                                       'prediction_weather_knowledge_tools_present': {'predict_next_attention', 'get_weather_forecast', 'search_plant_knowledge'} <= coverage,
                                                       'result': result})
                                report['normal_count'] = sum(row['normal_answer'] for row in report['runs'])
                                path.write_text(json.dumps(report, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
                                print(f'[verification.run] run={index} status={response.status_code} normal={normal}', file=log, flush=True)
                report['environment_samples_unchanged'] = before == db.get_samples(168)
    report['passed_4_of_5'] = report['normal_count'] >= 4
    report['finished_at'] = datetime.now(timezone.utc).isoformat()
    path.write_text(json.dumps(report, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    print(json.dumps({key: value for key, value in report.items() if key != 'runs'}, ensure_ascii=False, indent=2), flush=True)
    print(json.dumps([{'run': row['run'], 'http_status': row['http_status'], 'normal_answer': row['normal_answer'], 'tool_names': [call['tool'] for call in row['result'].get('tool_calls', [])]} for row in report['runs']], ensure_ascii=False, indent=2), flush=True)
    if not report['passed_4_of_5']:
        raise SystemExit(1)


if __name__ == '__main__':
    asyncio.run(verify())
