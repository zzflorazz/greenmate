"""Isolated browser fixture. No production import path or substitute live weather."""
from datetime import datetime, timedelta, timezone
import analysis
from main import app


def forecast_fixture(location):
    start=datetime.now(timezone.utc).replace(minute=0,second=0,microsecond=0)+timedelta(hours=1)
    return {'status':'ok','source':'OPEN_METEO_UI_FIXTURE','time':datetime.now(timezone.utc).isoformat(),
            'data':{'location':location,'items':[{'timestamp':(start+timedelta(hours=i)).isoformat(),'temperature':30+i*.5,'humidity':65} for i in range(12)]},'error':None}

async def explain_fixture(question,judgment):
    return '浏览器测试解释（非真实LLM）：'+judgment['adjustment_reason']

analysis.get_weather_forecast=forecast_fixture
analysis.explain_analysis=explain_fixture
