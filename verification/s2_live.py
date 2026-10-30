"""Real scenario API contrast. Export only the newly generated simulations."""
import asyncio
import hashlib
import json
import sys
from contextlib import redirect_stdout
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
import httpx2
import db
from main import app


async def verify():
    baseline=json.loads((ROOT/'verification/s2_baseline_hashes.json').read_text())
    snapshots={row['run_id']:db.get_analysis_run(row['run_id']) for row in db.list_analysis_runs(5)}
    results=[]
    with (ROOT/'verification/s2_live.log').open('w',encoding='utf-8') as log, redirect_stdout(log):
        async with app.router.lifespan_context(app):
            async with httpx2.AsyncClient(transport=httpx2.ASGITransport(app=app),base_url='http://greenmate.local') as client:
                prep=await client.post('/api/scenarios/apply',json={'name':'S1_stable'})
                prep.raise_for_status()
                anchor=prep.json()['analysis_time']
                for name in ('S1_stable','S2_ramp'):
                    response=await client.post('/api/analyze/scenario',json={'name':name,'analysis_time':anchor})
                    response.raise_for_status()
                    result=response.json()
                    assert result['run']['history_window']['count']==6
                    assert all(row['source_type']=='SIMULATED' and row['sim_scenario']==name for row in result['run']['history_window']['items'])
                    results.append(result)
                response=await client.get('/api/analyze/compare',params={'run_a':results[0]['run_id'],'run_b':results[1]['run_id']})
                response.raise_for_status()
                compare=response.json()
                repeat=(await client.post('/api/scenarios/apply',json={'name':'S2_ramp','analysis_time':anchor})).json()
    after={name:hashlib.sha256((ROOT/name).read_bytes()).hexdigest() for name in baseline}
    a,b=[item['run'] for item in results]
    report={'mode':'real_llm_same_analysis_pipeline_only_scenario_history_changed',
            'runs':results,'comparison':compare,'critical_files_unchanged':after==baseline,
            'old_archives_unchanged':all(db.get_analysis_run(key)==value for key,value in snapshots.items()),
            'same_current_values':a['judgment']['current_state']==b['judgment']['current_state'],
            'same_analysis_time':a['analysis_time']==b['analysis_time'],
            'fixed_question_match':compare['fixed_question_match'],
            'repeat_samples_written':repeat['samples_written'],
            'both_llm_explanations_completed':all(run['judgment']['explanation_status']=='ok' for run in (a,b)),
            'hashes':after}
    (ROOT/'verification/s2_live.json').write_text(json.dumps(report,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    print(json.dumps({key:value for key,value in report.items() if key not in ('runs','comparison','hashes')},ensure_ascii=False,indent=2),flush=True)
    print(json.dumps([{'run_id':run['run_id'],'current':run['judgment']['current_state'],'temperature_trend':run['judgment']['recent_trend']['metrics']['temperature'],'prediction':run['prediction']['prediction'],'P(WATCH)':run['prediction']['probability'],'answer':run['answer']} for run in (a,b)],ensure_ascii=False,indent=2),flush=True)
    assert report['critical_files_unchanged'] and report['same_current_values'] and report['old_archives_unchanged']
    assert a['judgment']['recent_trend']['metrics']['temperature']['direction']=='stable'
    assert b['judgment']['recent_trend']['metrics']['temperature']['direction']=='rising'
    assert repeat['samples_written']==0 and report['fixed_question_match']
    if not report['both_llm_explanations_completed']:
        raise SystemExit(1)


if __name__=='__main__':
    asyncio.run(verify())
