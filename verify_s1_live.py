"""Actual API + LLM + SQLite recall, limited to this task's S1 simulation."""
import asyncio
import hashlib
import json
import subprocess
import sys
from contextlib import redirect_stdout
from pathlib import Path

import httpx2
import db
from main import app

ROOT = Path(__file__).resolve().parent


async def verify():
    prepared = json.loads((ROOT / 's1_preparation.json').read_text())
    directory = ROOT / 'verification'
    directory.mkdir(exist_ok=True)
    model = ROOT / 'models/attention_v1.joblib'
    before_hash = hashlib.sha256(model.read_bytes()).hexdigest()
    with (directory / 's1_live.log').open('w', encoding='utf-8') as log, redirect_stdout(log):
        async with app.router.lifespan_context(app):
            before = db.get_samples_at(__import__('datetime').datetime.fromisoformat(prepared['analysis_time']), 3)
            # Do not export other history or state: this check requires only the
            # explicitly prepared, new S1 simulation and matching B02 snapshot.
            assert len(before) == 6 and all(row['source_type'] == 'SIMULATED' and row['sim_scenario'] == 's1_stable' for row in before)
            current = db.get_state_from_db()
            assert current['source_type'] == 'SIMULATED' and 29 <= current['temperature'] <= 30
            async with httpx2.AsyncClient(transport=httpx2.ASGITransport(app=app), base_url='http://greenmate.local') as client:
                response = await client.post('/api/analyze', json={'analysis_time': prepared['analysis_time'], 'location': '北京'})
                response.raise_for_status()
                run = response.json()
                recalled = (await client.get('/api/analyze/' + run['run_id'])).json()
            after = db.get_samples_at(__import__('datetime').datetime.fromisoformat(prepared['analysis_time']), 3)
    # New interpreter, not a page/session/cache; only SQLite + run_id required.
    code = 'import json,sys; from db import get_analysis_run; print(json.dumps(get_analysis_run(sys.argv[1]), ensure_ascii=False))'
    fresh = json.loads(subprocess.check_output([sys.executable, '-c', code, run['run_id']], cwd=ROOT, text=True))
    report = {'mode': 'real_api_real_llm_only_new_s1_simulation', 'run': run,
              'api_recall_identical': recalled == run, 'fresh_process_recall_identical': fresh == run,
              'samples_unchanged': before == after, 'model_unchanged': before_hash == hashlib.sha256(model.read_bytes()).hexdigest(),
              'history_end_equals_anchor': run['history_window']['end'] == run['analysis_time'],
              'llm_explanation_completed': run['judgment']['explanation_status'] == 'ok'}
    (directory / 's1_live.json').write_text(json.dumps(report, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    print(json.dumps({key: value for key, value in report.items() if key != 'run'}, ensure_ascii=False, indent=2), flush=True)
    print(json.dumps({'run_id': run['run_id'], 'evidence_status': run['evidence_status'], 'prediction': run['prediction'], 'answer': run['answer']}, ensure_ascii=False, indent=2), flush=True)
    if not report['llm_explanation_completed']:
        raise SystemExit(1)


if __name__ == '__main__':
    asyncio.run(verify())
