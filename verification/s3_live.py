"""S3 live check: only newly generated S1 simulation + existing public weather tool.

No archived user history is exported. No training, prompt or model changes.
"""
import asyncio
import hashlib
import json
import sys
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
import httpx2
import db
from main import app

async def verify():
    runs=[]
    async with app.router.lifespan_context(app):
        async with httpx2.AsyncClient(transport=httpx2.ASGITransport(app=app),base_url='http://greenmate.local') as client:
            prep=await client.post('/api/scenarios/apply',json={'name':'S1_stable'})
            prep.raise_for_status();anchor=prep.json()['analysis_time']
            rows=db.get_samples_at(__import__('datetime').datetime.fromisoformat(anchor),3)
            assert len(rows)==6 and all(r['source_type']=='SIMULATED' and r['sim_scenario']=='S1_stable' for r in rows)
            for flag in (False,True):
                response=await client.post('/api/analyze/scenario',json={'name':'S1_stable','analysis_time':anchor,'include_weather':flag})
                response.raise_for_status();run=response.json()['run'];runs.append(run)
                print(json.dumps({'run_id':run['run_id'],'include_weather':flag,'weather_status':run['evidence_status']['weather'],'explanation_status':run['judgment']['explanation_status']},ensure_ascii=False),flush=True)
                assert (await client.get('/api/analyze/'+run['run_id'])).json()==run
    a,b=runs
    baseline=json.loads((ROOT/'verification/s3_baseline_hashes.json').read_text())
    same_internal=all(a[k]==b[k] for k in ('history_window','prediction','question','analysis_time')) and a['state']['data']==b['state']['data']
    protected=all(hashlib.sha256((ROOT/p).read_bytes()).hexdigest()==v for p,v in baseline.items())
    weather=b['judgment']['weather_evidence']
    weather_valid=weather['status']=='ok' and all(__import__('datetime').datetime.fromisoformat(p['timestamp'])>=__import__('datetime').datetime.fromisoformat(b['analysis_time']) for p in weather['result']['items'])
    report={'weather_future_valid':weather_valid,'both_llm_explanations_completed':all(r['judgment']['explanation_status']=='ok' for r in runs),'mode':'real_existing_weather_tool_and_real_llm','same_internal_evidence':same_internal,'protected_assets_unchanged':protected,'runs':runs}
    (ROOT/'verification/s3_live.json').write_text(json.dumps(report,ensure_ascii=False,indent=2)+'\n')
    assert same_internal and protected
    print(json.dumps({'same_internal_evidence':same_internal,'protected_assets_unchanged':protected,'weather':b['judgment']['weather_evidence'],'adjustment':b['judgment']['adjustment_reason'],'answers':[r['answer'] for r in runs]},ensure_ascii=False),flush=True)

if __name__=='__main__':asyncio.run(verify())
