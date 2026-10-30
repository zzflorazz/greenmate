"""Browser-test fixture only; production main never imports this module."""
import analysis
import db
import prepare_s1 as preparation
from pathlib import Path
from main import app
from prepare_s1 import prepare_s1

preparation.PREPARATION_PATH = Path(db._database_path()).with_suffix('.s1.json')
prepare_s1()


async def fixture_explanation(question, judgment):
    prediction = judgment['predicted_attention']
    return ('浏览器测试解释（非真实LLM）：程序记录稳定段，已保存模型输出'
            + str(prediction.get('prediction')) + '，版本' + str(prediction.get('model_version'))
            + '。SIMULATED与MODEL_OUTPUT不能代替土壤湿度或天气证据。')


analysis.explain_analysis = fixture_explanation
