"""Offline UI fixture server. Never presented as real-weather/live-LLM evidence."""
import os
from pathlib import Path
import sys
from unittest.mock import patch
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
os.environ['DB_PATH']=str(ROOT/'verification/s4_ui.db')
import db
import state
import analysis
from main import app
from test_s3_weather import forecast
import uvicorn

def weather(location):
    from datetime import datetime,timezone
    data=forecast(datetime.now(timezone.utc),temperatures=(20,17,14))
    data['source']='OPEN_METEO_UI_FIXTURE'
    return data

async def explain(question,judgment):
    return 'UI测试解释（非真实LLM）：内部历史升温与外部预报降温有分歧。模型原始标签保留。'+('番茄知识tomato_heat_01作为条件性关注参考。' if judgment['knowledge'].get('citation') else '知识关闭或不可用。')+'缺内部后续实测与生育期。conclusion_level=conflicting。'

if __name__=='__main__':
    db.init_db();state.load_state()
    with patch('analysis.get_weather_forecast',side_effect=weather),patch('analysis.explain_analysis',side_effect=explain):
        # Use the already built real index/model; no mocked knowledge results.
        uvicorn.run(app,host='127.0.0.1',port=18114)
