"""Four evidence tools plus model inference, with a shared result envelope."""
import math
from datetime import datetime, timedelta, timezone

import requests

from settings import WEATHER_LAT, WEATHER_LON
from db import get_samples
from rag import vector_search
from state import get_state
from ml_infer import predict_latest


def tool_result(status: str, source: str, data: dict | None = None, error: str | None = None) -> dict:
    return {"status": status, "source": source, "time": datetime.now(timezone.utc).isoformat(), "data": data if data is not None else {}, "error": error}


def get_current_environment() -> dict:
    try:
        current = get_state()
    except RuntimeError:
        return tool_result("unavailable", "CURRENT_STATE", error="当前环境状态尚未加载，当前读数证据缺失。")
    return tool_result("ok", current["source_type"], current)


def get_environment_history(hours=24) -> dict:
    if type(hours) not in (int, float) or not math.isfinite(hours) or not 0 < hours <= 168:
        return tool_result("error", "SQLITE", error="hours 必须是大于0且不超过168的数值；本次未取得历史数据。")
    try:
        samples = get_samples(hours)
    except Exception as error:
        return tool_result("unavailable", "SQLITE", error=f"历史数据库读取失败（{type(error).__name__}），历史数据证据缺失。")
    sources = {sample["source_type"] for sample in samples}
    source = next(iter(sources)) if len(sources) == 1 else ("MIXED" if sources else "SQLITE")
    return tool_result("ok", source, {"hours": hours, "items": samples, "count": len(samples)})


def get_weather_forecast(location: str) -> dict:
    # Retain the single configured location from B03; no geocoding or city switcher.
    if not isinstance(location, str) or location.strip().casefold() not in {"北京", "beijing", "配置地点", "当前地点"}:
        return tool_result("error", "OPEN_METEO", error="location 仅支持配置地点：北京（或 Beijing、配置地点、当前地点）。")
    start = datetime.now(timezone.utc).replace(minute=0, second=0, microsecond=0) + timedelta(hours=1)
    end = start + timedelta(hours=11)
    try:
        with requests.get(
            "https://api.open-meteo.com/v1/forecast",
            params={
                "latitude": WEATHER_LAT, "longitude": WEATHER_LON,
                "hourly": "temperature_2m,relative_humidity_2m",
                "temperature_unit": "celsius", "timezone": "UTC",
                "start_hour": start.strftime("%Y-%m-%dT%H:%M"),
                "end_hour": end.strftime("%Y-%m-%dT%H:%M"),
            },
            headers={"User-Agent": "GreenMate/1.0"},
            timeout=5, allow_redirects=False,
        ) as response:
            if response.status_code != 200:
                raise ValueError(f"HTTP {response.status_code}")
            hourly = response.json()["hourly"]
        times, temperatures, humidities = hourly["time"], hourly["temperature_2m"], hourly["relative_humidity_2m"]
        if not (len(times) == len(temperatures) == len(humidities) == 12):
            raise ValueError("Incomplete 12-hour forecast")
        items = []
        for index, (timestamp, temperature, humidity) in enumerate(zip(times, temperatures, humidities)):
            moment = datetime.fromisoformat(timestamp)
            moment = moment.replace(tzinfo=timezone.utc) if moment.tzinfo is None else moment.astimezone(timezone.utc)
            if moment != start + timedelta(hours=index):
                raise ValueError("Unexpected forecast timestamp")
            if any(type(value) not in (int, float) or not math.isfinite(value) for value in (temperature, humidity)) or not 0 <= humidity <= 100:
                raise ValueError("Invalid weather values")
            items.append({"timestamp": moment.isoformat(), "temperature": temperature, "humidity": humidity})
        return tool_result("ok", "OPEN_METEO", {
            "location": location, "latitude": float(WEATHER_LAT), "longitude": float(WEATHER_LON),
            "hours": 12, "timezone": "UTC", "units": {"temperature": "°C", "humidity": "%"}, "items": items,
        })
    except requests.Timeout:
        reason = "天气API超时（5秒），未来12小时预报证据缺失。"
    except requests.RequestException:
        reason = "天气API网络请求失败，未来12小时预报证据缺失。"
    except (ValueError, KeyError, TypeError, OverflowError):
        reason = "天气API返回非200响应或无效预报，未来12小时预报证据缺失。"
    print(f"[weather.forecast] unavailable: {reason}", flush=True)
    return tool_result("unavailable", "OPEN_METEO", error=reason)


def search_plant_knowledge(query: str) -> dict:
    if not isinstance(query, str) or not query.strip() or len(query) > 2000:
        return tool_result("error", "LOCAL_KNOWLEDGE", error="query 必须是非空字符串，且不超过2000字。")
    try:
        items = vector_search(query)
    except Exception as error:
        return tool_result("unavailable", "LOCAL_KNOWLEDGE", error=f"知识检索不可用（{type(error).__name__}），本地知识证据缺失。")
    return tool_result("ok", "LOCAL_KNOWLEDGE", {"query": query, "items": items})


def predict_next_attention() -> dict:
    prediction = predict_latest()
    return tool_result(prediction['status'], 'MODEL_OUTPUT', prediction, prediction.get('error'))


TOOL_SCHEMAS = [
    {"type": "function", "function": {
        "name": "get_current_environment", "description": "读取当前温度、空气湿度、光照及数据来源，不修改状态。",
        "parameters": {"type": "object", "properties": {}, "required": [], "additionalProperties": False},
    }},
    {"type": "function", "function": {
        "name": "get_environment_history", "description": "读取SQLite中最近hours小时的历史样本，按时间升序；默认24小时，合法范围0<hours<=168。SIMULATED/seed_demo是演示历史，不是真实测量。",
        "parameters": {"type": "object", "properties": {"hours": {"type": "number", "default": 24, "exclusiveMinimum": 0, "maximum": 168}}, "required": [], "additionalProperties": False},
    }},
    {"type": "function", "function": {
        "name": "get_weather_forecast", "description": "获取配置地点（示例北京）从下一个整点起未来12小时的逐小时天气预报。不修改当前状态。网络失败返回unavailable。",
        "parameters": {"type": "object", "properties": {"location": {"type": "string", "description": "配置地点名称，例如北京"}}, "required": ["location"], "additionalProperties": False},
    }},
    {"type": "function", "function": {
        "name": "search_plant_knowledge", "description": "用向量检索本地植物知识（模型失败时回退关键词）。无匹配是正常结果：status=ok，data.items=[]。中文排序有局限。",
        "parameters": {"type": "object", "properties": {"query": {"type": "string", "minLength": 1, "maxLength": 2000}}, "required": ["query"], "additionalProperties": False},
    }},
    {"type": "function", "function": {
        "name": "predict_next_attention", "description": "用持久化attention_v1预测最新连续窗口之后一小时是否需关注，返回P(WATCH)、模型版本、窗口时间和MODEL_OUTPUT证据类型。仅适用于SIMULATED规则标签；不能替代天气、历史、植物知识证据，不修改任何数据。",
        "parameters": {"type": "object", "properties": {}, "required": [], "additionalProperties": False},
    }},
]

TOOL_FUNCTIONS = {
    "get_current_environment": get_current_environment,
    "get_environment_history": get_environment_history,
    "get_weather_forecast": get_weather_forecast,
    "search_plant_knowledge": search_plant_knowledge,
    "predict_next_attention": predict_next_attention,
}
