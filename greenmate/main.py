import json
from pathlib import Path
from contextlib import asynccontextmanager
from asyncio import Lock, to_thread
from typing import Literal
from fastapi import FastAPI, HTTPException, Query, Request
from fastapi.exceptions import RequestValidationError
from starlette.exceptions import HTTPException as StarletteHTTPException
from fastapi.responses import HTMLResponse, JSONResponse
from openai import APITimeoutError, AuthenticationError, OpenAIError, RateLimitError
from pydantic import BaseModel, ConfigDict, Field, field_validator

from llm import EmptyAnswerError, MissingAPIKeyError, generate_answer
from db import init_db, load_recent_chat, save_chat, get_samples
from state import DEFAULT_STATE, get_state, load_state, update_state
from settings import WEATHER_LAT, WEATHER_LON, get_settings
from api_errors import failure, hint_for
from weather import fetch_weather
from rag import build_knowledge_index, get_knowledge, load_knowledge, vector_search
from agent import AgentRunError, run_agent
from ml_dataset import dataset_summary
from ml_infer import predict_latest
from llm_retry import error_details
from analysis import ANALYSIS_QUESTION, run_analysis
from db import get_analysis_run, list_analysis_runs
from scenarios import apply_scenario, compare_runs


class StateUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    # Fields may be omitted, but explicitly supplied values must be numbers.
    temperature: float = Field(default=None)
    humidity: float = Field(default=None)
    light: float = Field(default=None)


class SourceRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    source: Literal["SIMULATED", "REAL_WEATHER"]


class AskRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    question: str = Field(min_length=1, max_length=2000)

    @field_validator("question")
    @classmethod
    def strip_question(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("问题不能为空")
        return value


class AgentRequest(AskRequest):
    allow_write: bool = Field(default=False, strict=True, description="兼容旧客户端；当前五工具均只取证，该字段不启用写操作。")


class AnalysisRequest(BaseModel):
    model_config = ConfigDict(extra='forbid')
    analysis_time: str | None = None
    location: str = Field(default='北京', min_length=1, max_length=100)
    include_weather: bool = Field(default=False, strict=True)
    include_knowledge: bool = Field(default=False, strict=True)


class ScenarioRequest(BaseModel):
    model_config = ConfigDict(extra='forbid')
    name: Literal['S1_stable', 'S2_ramp', 'S4_conflict']
    analysis_time: str | None = None


class ScenarioAnalysisRequest(ScenarioRequest):
    include_weather: bool = Field(default=False, strict=True)
    include_knowledge: bool = Field(default=False, strict=True)


@asynccontextmanager
async def lifespan(app: FastAPI):
    get_settings().report_startup()
    init_db()
    load_state()
    load_knowledge()
    try:
        await to_thread(build_knowledge_index)
    except Exception as error:
        print(f"[rag] 向量索引初始化失败，使用关键词回退：{type(error).__name__}。")
    yield


app = FastAPI(lifespan=lifespan)
scenario_lock = Lock()
PAGE_PATH = Path(__file__).with_name("index.html")
METRICS_PATH = Path(__file__).with_name("ml_metrics.json")


@app.exception_handler(StarletteHTTPException)
async def http_error_handler(request: Request, error: StarletteHTTPException):
    message = error.detail if isinstance(error.detail, str) else '请求处理失败。'
    message = {'Not Found': '未找到请求的页面或接口。',
               'Method Not Allowed': '此接口不支持当前请求方式。',
               'Unauthorized': '请求未通过验证。', 'Forbidden': '无法执行此请求。'}.get(message, message)
    hint = hint_for(error.status_code)
    if error.status_code in (502, 503, 504) and request.url.path in ('/api/set-source', '/api/fetch-weather'):
        hint = '请检查网络与 WEATHER_LAT/WEATHER_LON 配置后重试；当前状态会保留，天气接口无需密钥。'
    return failure(error.status_code, f'HTTP_{error.status_code}', message, hint, detail=message)


@app.exception_handler(RequestValidationError)
async def validation_error_handler(request: Request, error: RequestValidationError):
    return failure(422, 'INVALID_REQUEST', '输入内容不符合要求。',
                   '请填写问题或搜索词，并检查输入类型及长度。', detail='输入内容不符合要求。')


@app.exception_handler(AgentRunError)
async def agent_error_handler(request: Request, error: AgentRunError):
    return failure(error.status_code, 'LLM_UNAVAILABLE', error.result['llm_error']['message'],
                   hint_for(error.status_code), **error.result)


@app.exception_handler(Exception)
async def unexpected_error_handler(request: Request, error: Exception):
    print(f'[api.error] {request.method} {request.url.path}: {type(error).__name__}', flush=True)
    return failure(500, 'INTERNAL_ERROR', '服务暂时无法完成请求。', hint_for(500))


@app.get("/api/ml/metrics")
def read_ml_metrics():
    try:
        return json.loads(METRICS_PATH.read_text(encoding="utf-8"))
    except FileNotFoundError:
        raise HTTPException(404, "评估结果尚未生成，请先运行 .venv/bin/python ml_train.py。") from None
    except (OSError, ValueError):
        raise HTTPException(500, "评估结果文件无法读取，请重新运行 ml_train.py。") from None


@app.get("/api/ml/dataset/summary")
def read_ml_dataset_summary():
    return dataset_summary()


@app.get("/api/ml/predict")
def read_ml_prediction():
    prediction = predict_latest()
    if prediction['status'] != 'ok':
        message = prediction.get('error') or '当前窗口无法预测。'
        return failure(503, 'PREDICTION_UNAVAILABLE', message,
                       '请检查模型文件与最新连续采样；服务不会自动重训或用旧窗口补齐。',
                       **{key: value for key, value in prediction.items() if key != 'error'})
    return prediction


@app.get("/", response_class=HTMLResponse)
def root():
    return HTMLResponse(PAGE_PATH.read_text(encoding="utf-8"))


@app.get("/api/state")
async def read_state():
    return get_state()


@app.post('/api/analyze')
async def analyze(request: AnalysisRequest | None = None):
    data = request or AnalysisRequest()
    try:
        return await run_analysis(data.analysis_time, data.location, data.include_weather, data.include_knowledge)
    except ValueError as error:
        raise HTTPException(400, str(error)) from None


@app.get('/api/analyze')
def recent_analyses():
    return {'question': ANALYSIS_QUESTION, 'items': list_analysis_runs(5)}


@app.post('/api/scenarios/apply')
async def apply_named_scenario(request: ScenarioRequest):
    try:
        async with scenario_lock:
            return apply_scenario(request.name, request.analysis_time)
    except ValueError as error:
        raise HTTPException(400, str(error)) from None


@app.post('/api/analyze/scenario')
async def analyze_named_scenario(request: ScenarioAnalysisRequest):
    try:
        async with scenario_lock:
            prepared = apply_scenario(request.name, request.analysis_time)
            record = await run_analysis(prepared['analysis_time'], '北京', request.include_weather, request.include_knowledge)
        return {'run_id': record['run_id'], 'scenario': prepared, 'run': record}
    except ValueError as error:
        raise HTTPException(400, str(error)) from None


@app.get('/api/analyze/compare')
def compare_analyses(run_a: str, run_b: str):
    try:
        return compare_runs(run_a, run_b)
    except LookupError as error:
        raise HTTPException(404, str(error)) from None


@app.get('/api/analyze/{run_id}')
def read_analysis(run_id: str):
    record = get_analysis_run(run_id)
    if record is None:
        raise HTTPException(404, '未找到该run_id，请检查编号是否完整。')
    return record


@app.post("/api/state")
async def change_state(changes: StateUpdate):
    return update_state(changes.model_dump(exclude_unset=True))


@app.post("/api/fetch-weather")
async def fetch_current_weather():
    # requests is synchronous; keep the event loop available during the HTTP call.
    weather = await to_thread(fetch_weather, WEATHER_LAT, WEATHER_LON)
    if weather is None:
        raise HTTPException(502, "获取真实天气失败，请检查网络和 WEATHER_LAT/WEATHER_LON 配置后重试；现有状态未改变。")
    # This API does not supply light: retain the existing value without inventing one.
    return update_state(weather, source_type="REAL_WEATHER")


@app.post("/api/set-source")
async def set_source(request: SourceRequest):
    if request.source == "SIMULATED":
        return update_state(DEFAULT_STATE, source_type="SIMULATED")
    return await fetch_current_weather()


@app.post("/api/ask")
async def ask(request: AskRequest):
    # Keep the exact snapshot sent to the model, even if state changes meanwhile.
    used_state = get_state()
    knowledge = await to_thread(vector_search, request.question)
    # Read earlier messages before saving this question, so it is sent only once.
    history = load_recent_chat(10)
    save_chat("user", request.question)
    try:
        answer = await generate_answer(used_state, request.question, history, knowledge=knowledge or None)
    except (MissingAPIKeyError, OpenAIError, EmptyAnswerError) as error:
        if isinstance(error, MissingAPIKeyError):
            status, message = 503, "请在启动服务前设置环境变量 GREENMATE_API_KEY。"
        elif isinstance(error, AuthenticationError):
            status, message = 502, "模型平台鉴权失败，请检查 GREENMATE_API_KEY 和平台配置。"
        elif isinstance(error, RateLimitError):
            status, message = 503, "模型平台限流或额度不足，请检查账户后重试。"
        elif isinstance(error, APITimeoutError):
            status, message = 504, "模型响应超时，请稍后重试。"
        else:
            status, message = 502, "模型调用失败或未返回有效回答，请检查平台配置后重试。"
        return failure(status, 'LLM_UNAVAILABLE', message, hint_for(status), **{
            "detail": message, "llm_error": error_details(error, message),
            "used_state": used_state, "source_type": used_state["source_type"],
            "tool_calls": [],
        })
    save_chat("assistant", answer)
    return {
        "answer": answer,
        "used_state": used_state,
        "source_type": used_state["source_type"],
    }


@app.get("/api/history")
async def read_history():
    return load_recent_chat(20)


@app.get('/api/environment/history')
def read_environment_history():
    items = get_samples(24)
    sources = {item['source_type'] for item in items}
    return {'hours': 24, 'items': items, 'count': len(items),
            'source': next(iter(sources)) if len(sources) == 1 else ('MIXED' if sources else 'SQLITE')}


@app.post("/api/agent")
async def agent_question(request: AgentRequest):
    return await run_agent(request.question, allow_write=request.allow_write)


@app.get('/api/knowledge/search')
async def search_knowledge(query: str = Query(min_length=1, max_length=2000)):
    query = query.strip()
    if not query:
        raise HTTPException(400, '请填写植物名称或养护问题。')
    return {'query': query, 'items': await to_thread(vector_search, query),
            'evidence_type': 'LOCAL_KNOWLEDGE'}


@app.get("/api/knowledge")
async def read_knowledge():
    return get_knowledge()


@app.post("/api/knowledge/reload")
async def reload_knowledge():
    try:
        knowledge = load_knowledge()
    except (OSError, ValueError):
        raise HTTPException(400, "知识库重载失败，请检查 knowledge/plants.json 的文件和内容格式；原知识缓存保留。") from None
    try:
        await to_thread(build_knowledge_index, force=True)
    except Exception as error:
        print(f"[rag] 向量索引重建失败：{type(error).__name__}。")
        return {"message": "知识库已重新加载；向量索引重建失败，检索不可用时将回退关键词。", "count": len(knowledge), "index_ready": False}
    return {"message": "知识库已重新加载并重建向量索引", "count": len(knowledge), "index_ready": True}
