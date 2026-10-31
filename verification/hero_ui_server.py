"""Isolated UI verification only. No production imports this fixture module.

Uses real state/SQLite/scenarios/model/RAG. External weather/LLM are explicit
fixtures so the page regression never sends user data or needs network access.
"""
from datetime import datetime, timedelta, timezone
import os
import analysis
import db
import main
import state
from scenarios import apply_scenario

app = main.app

def forecast(location):
    start = datetime.now(timezone.utc) + timedelta(hours=1)
    return {'status':'ok','source':'OPEN_METEO_UI_FIXTURE','time':datetime.now(timezone.utc).isoformat(),
            'data':{'location':location,'items':[{'timestamp':(start+timedelta(hours=i)).isoformat(),'temperature':20-i*.5,'humidity':65} for i in range(12)]},'error':None}

async def explain(question, judgment):
    return '页面测试解释（非真实LLM）：'+judgment['adjustment_reason']+'；所有原始证据均已保存。'

if os.getenv('GREENMATE_UI_LIVE_WEATHER') != '1':
    main.fetch_weather = lambda *args: {'temperature':34,'humidity':95,'source_type':'REAL_WEATHER'}
analysis.get_weather_forecast = forecast
analysis.explain_analysis = explain
# Leave production database and model untouched.
db.init_db()
apply_scenario('S1_stable')
state.load_state()
