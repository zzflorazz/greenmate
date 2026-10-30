"""Optional real-model integration check; uses the normal agent, no forced order."""
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


async def verify() -> None:
    directory = Path(__file__).resolve().parent / 'verification'
    directory.mkdir(exist_ok=True)
    question = '请分别查看当前环境、最近24小时历史、北京未来12小时天气预报，再搜索本地知识“不存在的内容xyz”。请逐项说明证据来源、是否可用，以及哪些证据缺失。不要把模拟历史当作真实观测。'
    # Only task-generated synthetic values leave this process. Never read the
    # user's existing current_state/environment_samples for this network check.
    with TemporaryDirectory(prefix='greenmate-b05-public-demo-') as temp_dir:
        with patch('db.DB_PATH', str(Path(temp_dir) / 'synthetic.db')), patch('tools.WEATHER_LAT', '39.9'), patch('tools.WEATHER_LON', '116.4'):
            with (directory / 'b05_live.log').open('w', encoding='utf-8') as log, redirect_stdout(log):
                seed_history()
                async with app.router.lifespan_context(app):
                    before = db.get_state_from_db()
                    try:
                        result = await agent.run_agent(question)
                        status = 'completed'
                    except agent.AgentRunError as error:
                        result = error.result
                        status = 'model_error'
                    after = db.get_state_from_db()
    report = {
        'mode': 'real_model_and_registered_tools_no_forced_order',
        'data_scope': 'new_temporary_database_with_generated_SIMULATED_seed_demo_only; public_Beijing_coordinates',
        'time': datetime.now(timezone.utc).isoformat(),
        'question': question, 'status': status, 'current_state_unchanged': before == after,
        'result': result,
    }
    (directory / 'b05_live.json').write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding='utf-8')
    print(json.dumps({
        'status': status, 'current_state_unchanged': before == after,
        'iterations': result['iterations'],
        'calls': [{'sequence': call['sequence'], 'tool': call['tool'], 'status': call['status'], 'elapsed_ms': call['elapsed_ms']} for call in result['tool_calls']],
        'answer': result['answer'],
    }, ensure_ascii=False, indent=2), flush=True)
    if status != 'completed':
        raise SystemExit(1)


if __name__ == '__main__':
    asyncio.run(verify())
