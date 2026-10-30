"""Live S4 verification: real B05 knowledge/weather tools and existing LLM/model.

Runs against a separate DB; exports only this newly generated simulation and its
public forecast. Credentials are loaded from the source project's .env, never logged.
"""
import asyncio
import hashlib
import json
import os
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
# Optional credential path for verifying a staging copy without copying secrets.
if os.environ.get('GREENMATE_S4_ENV_PATH'):
    from dotenv import load_dotenv
    load_dotenv(os.environ['GREENMATE_S4_ENV_PATH'], override=False)
os.environ['DB_PATH'] = os.environ.get('GREENMATE_S4_DB', str(ROOT / 'verification' / 's4_live.db'))
import db
from analysis import run_analysis, ANALYSIS_QUESTION
from evidence import FORBIDDEN
from scenarios import apply_scenario
from rag import load_knowledge


async def verify():
    db.init_db()
    load_knowledge()
    prepared = apply_scenario('S4_conflict')
    runs = []
    for enabled in (True, False):
        run = await run_analysis(prepared['analysis_time'], include_weather=True, include_knowledge=enabled)
        runs.append(run)
        print(json.dumps({'run_id':run['run_id'],'include_knowledge':enabled,'model':run['prediction'].get('prediction'),
                          'weather':run['evidence_status']['weather'],'conclusion_level':run['judgment']['conclusion_level'],
                          'adopted_sources':[e['source_type'] for e in run['judgment']['evidence_records'] if e['status']=='ok'],
                          'explanation_status':run['judgment']['explanation_status']},ensure_ascii=False),flush=True)
    a,b = runs
    baseline=json.loads((ROOT/'verification/s3_baseline_hashes.json').read_text())
    checks = {
        'protected_assets_unchanged': all(hashlib.sha256((ROOT/name).read_bytes()).hexdigest()==digest for name,digest in baseline.items() if name != 'tools.py'),
        'weather_transport_header_only': hashlib.sha256((ROOT/'tools.py').read_text().replace('            },\n            headers={"User-Agent": "GreenMate/1.0"},\n            timeout=5, allow_redirects=False,','            }, timeout=5, allow_redirects=False,').encode()).hexdigest()==baseline['tools.py'],
        'fixed_question_unchanged': all(r['question']==ANALYSIS_QUESTION for r in runs),
        'five_sources': len(a['judgment']['evidence_records'])==5,
        'knowledge_off_four_sources': sum(e['status']=='ok' for e in b['judgment']['evidence_records'])==4 and any(e['source_type']=='KNOWLEDGE' and e['status']=='unavailable' and e['result'] is None for e in b['judgment']['evidence_records']) and b['judgment']['knowledge']['status']=='unavailable',
        'explicit_conflict': bool(a['judgment']['conflicts']) and a['judgment']['conclusion_level']=='conflicting',
        'knowledge_really_called_and_adopted': any(t['tool']=='search_plant_knowledge' and t['adopted'] for t in a['tool_trace']),
        'knowledge_off_not_called': not any(t['tool']=='search_plant_knowledge' for t in b['tool_trace']),
        'explanations_completed': all(r['judgment']['explanation_status']=='ok' and r['answer'] for r in runs),
        'no_absolutes': all(not FORBIDDEN.search(r['answer']) for r in runs),
        'model_and_history_unchanged_between_runs': a['prediction']==b['prediction'] and a['history_window']==b['history_window'],
        'future_forecast_valid': all(__import__('datetime').datetime.fromisoformat(i['timestamp']) >= __import__('datetime').datetime.fromisoformat(a['analysis_time']) for i in a['judgment']['weather_evidence']['result']['items']) and a['evidence_status']['weather']=='ok',
        'archives_recall_exactly': all(db.get_analysis_run(r['run_id'])==r for r in runs),
    }
    report={'mode':'real_registered_tools_real_forecast_real_saved_model_real_llm','checks':checks,'runs':runs}
    (ROOT/'verification/s4_live.json').write_text(json.dumps(report,ensure_ascii=False,indent=2)+'\n')
    print(json.dumps(checks,ensure_ascii=False),flush=True)
    if not all(checks.values()):
        raise SystemExit('S4 live checks incomplete; see truthful report, do not alter model/forecast.')

if __name__=='__main__': asyncio.run(verify())
