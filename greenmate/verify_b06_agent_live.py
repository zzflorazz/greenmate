"""Real-model verification using freshly generated synthetic DB data only."""
import asyncio
import json
from contextlib import redirect_stdout
from datetime import datetime, timezone
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

import agent
import db
from main import app
from seed_history import seed_history


async def verify():
    directory = Path(__file__).with_name('verification')
    directory.mkdir(exist_ok=True)
    question = '预测接下来一小时要不要关注，并结合天气和养护知识说明。请区分模型预测、天气证据、养护知识，说明不确定性和模型适用边界。'
    with TemporaryDirectory(prefix='greenmate-b06-public-demo-') as temp_dir:
        with patch('db.DB_PATH', str(Path(temp_dir) / 'synthetic.db')), patch('tools.WEATHER_LAT', '39.9'), patch('tools.WEATHER_LON', '116.4'):
            with (directory / 'b06_agent_live.log').open('w', encoding='utf-8') as log, redirect_stdout(log):
                seed_history()
                before = db.get_samples(168)
                async with app.router.lifespan_context(app):
                    try:
                        result = await agent.run_agent(question)
                        status = 'completed'
                    except agent.AgentRunError as error:
                        result, status = error.result, 'model_error'
                after = db.get_samples(168)
    report = {'mode': 'real_model_registered_tools_no_forced_order',
              'data_scope': 'fresh_temporary_SIMULATED_seed_demo_only_and_public_Beijing_coordinates',
              'time': datetime.now(timezone.utc).isoformat(), 'question': question,
              'status': status, 'environment_samples_unchanged': before == after, 'result': result}
    (directory / 'b06_agent_live.json').write_text(json.dumps(report, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    print(json.dumps(report, ensure_ascii=False, indent=2), flush=True)
    if status != 'completed':
        raise SystemExit(1)


if __name__ == '__main__':
    asyncio.run(verify())
