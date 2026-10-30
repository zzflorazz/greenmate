"""Anchored existing evidence -> deterministic judgment -> LLM explanation.

S4 adds registered knowledge retrieval, evidence adoption and unresolved conflicts. No training.
"""
import math
from copy import deepcopy
from datetime import datetime, timedelta, timezone
from typing import Final
from uuid import uuid4

from asyncio import to_thread
from openai import OpenAIError

import db
from llm import EmptyAnswerError, MissingAPIKeyError
from evidence import (normalize_evidence, knowledge_query, valid_knowledge_items, standardize,
                      adoption, assess_conflicts, explanation_issue, explain_s4 as explain_analysis)
from tools import TOOL_FUNCTIONS
from llm_retry import error_details
from ml_dataset import INTERVAL, _moment
from ml_infer import predict_window
from tools import get_current_environment, get_weather_forecast

ANALYSIS_QUESTION: Final = '分析当前番茄生长环境状态以及接下来值得关注的变化，并说明判断依据。'
# Descriptive display tolerances, not agronomic risk thresholds or a new labeler.
# They only classify first-to-last movement; they NEVER change the saved model output.
TREND_TOLERANCES = {'temperature': 0.5, 'humidity': 2.0, 'light': 1000.0}


def normalize_time(value=None) -> datetime:
    try:
        anchor = datetime.now(timezone.utc) if value is None else (_moment(value) if isinstance(value, str) else value)
    except (ValueError, TypeError):
        raise ValueError('analysis_time 必须是带时区的有效 ISO 时间，例如 2026-10-21T20:00:00+08:00。') from None
    if not isinstance(anchor, datetime) or anchor.tzinfo is None:
        raise ValueError('analysis_time 必须是带时区的 ISO 时间，例如 2026-10-21T20:00:00+08:00。')
    anchor = anchor.astimezone(timezone.utc)
    if anchor > datetime.now(timezone.utc):
        raise ValueError('analysis_time 不能晚于当前时间。')
    return anchor


def _history(anchor: datetime) -> dict:
    evidence = {'status': 'unavailable', 'start': (anchor - timedelta(hours=3)).isoformat(),
                'end': anchor.isoformat(), 'interval': '(start, end]', 'hours': 3,
                'items': [], 'count': 0, 'source': 'SQLITE', 'error': None}
    try:
        rows = db.get_samples_at(anchor, 3)
        evidence.update(items=rows, count=len(rows))
        if len(rows) < 6:
            evidence['error'] = '最近3小时不足6个点，不能形成连续证据窗口。'
            return evidence
        times = [_moment(row['timestamp']) for row in rows]
        if any(right - left != INTERVAL for left, right in zip(times, times[1:])) or anchor - times[-1] > INTERVAL:
            evidence['error'] = '最近3小时存在断档、重复时间或末点距锚点超过30分钟。'
            return evidence
        if any(type(row[key]) not in (int, float) or not math.isfinite(row[key])
               for row in rows for key in TREND_TOLERANCES):
            evidence['error'] = '历史窗口有缺失或无效数值。'
            return evidence
        sources = {row['source_type'] for row in rows}
        evidence.update(status='ok', source=next(iter(sources)) if len(sources) == 1 else 'MIXED')
    except Exception as error:
        evidence['error'] = f'历史读取不可用（{type(error).__name__}）。'
    return evidence


def _trend(history: dict) -> dict:
    if history['status'] != 'ok':
        return {'status': 'unavailable', 'reason': history['error'], 'metrics': {}}
    metrics = {}
    for key, tolerance in TREND_TOLERANCES.items():
        values = [row[key] for row in history['items']]
        delta = values[-1] - values[0]
        metrics[key] = {'direction': 'stable' if abs(delta) <= tolerance else ('rising' if delta > 0 else 'falling'),
                        'first': values[0], 'last': values[-1], 'delta': round(delta, 6),
                        'mean': sum(values) / len(values), 'min': min(values), 'max': max(values),
                        'display_tolerance': tolerance}
    return {'status': 'ok', 'method': 'first_to_last_delta_with_display_tolerance', 'metrics': metrics,
            'note': '趋势描述不等于适宜性或风险规则；首尾相近不代表中间完全无波动，需同时看min/max。'}


def _weather(anchor: datetime, location: str, enabled: bool, trace=None) -> dict:
    """Normalize the existing tool envelope; only adopted points reach judgment/LLM.

    retrieved_at is retrieval time, not forecast validity time. Missing/invalid
    timestamps cannot be used as evidence. Filtering uses aware UTC instants,
    including microseconds, rather than lexicographic comparisons.
    """
    evidence = {'source_type': 'WEATHER_FORECAST', 'source': None, 'provider': None,
                'time': None, 'retrieved_at': None, 'forecast_time': None,
                'analysis_time': anchor.isoformat(), 'status': 'unavailable',
                'result': {'items': []}, 'error': '本次未启用外部天气证据。'}
    if not enabled:
        evidence.update(source='OPEN_METEO', time=anchor.isoformat(), result=None,
                        error='本次分析未启用天气预报（include_weather=false）')
        return evidence
    # This is the ONLY weather access in the analysis chain (no new request path).
    try:
        tool = get_weather_forecast(location)
    except Exception as error:
        tool = {'status': 'error', 'source': 'OPEN_METEO', 'time': datetime.now(timezone.utc).isoformat(),
                'data': {}, 'error': f'天气工具执行失败（{type(error).__name__}）。'}
    if trace is not None:
        trace.append({'tool': 'get_weather_forecast', 'status': tool['status'], 'adopted': False,
                      'adopt_reason': '尚未完成预报时间校验。', 'arguments': {'location': location}, 'source_type': 'WEATHER_FORECAST'})
    evidence.update(source=tool.get('source'), provider=tool.get('source'),
                    time=tool.get('time'), retrieved_at=tool.get('time'),
                    status=tool['status'], error=tool.get('error'))
    if tool['status'] != 'ok':
        return evidence
    try:
        retrieved = datetime.fromisoformat(tool['time'])
        if retrieved.tzinfo is None:
            raise ValueError('missing retrieval timezone')
        data = deepcopy(tool['data'])
        items = data.pop('items')
        accepted = []
        for item in items:
            moment = datetime.fromisoformat(item['timestamp'])
            if moment.tzinfo is None:
                raise ValueError('missing forecast timezone')
            if any(type(item.get(key)) not in (int, float) or not math.isfinite(item[key])
                   for key in ('temperature', 'humidity')):
                raise ValueError('invalid forecast values')
            if moment >= anchor:
                accepted.append((moment, item))
        accepted.sort(key=lambda pair: pair[0])
        evidence['excluded_past_count'] = len(items) - len(accepted)
        if not accepted:
            evidence.update(status='error', error='预报时间早于分析时刻，未采用任何预报点。' if items else '天气工具未返回预报点。')
            return evidence
        # No discarded past values are passed to the LLM as future evidence.
        data['items'] = [item for _, item in accepted]
        data['hours'] = len(accepted)
        evidence.update(result=data, forecast_time={'start': accepted[0][0].isoformat(),
                        'end': accepted[-1][0].isoformat()}, error=None)
    except (KeyError, TypeError, ValueError, OverflowError):
        evidence.update(status='error', error='天气工具返回了无效数值或缺少带时区的预报/获取时间。', result={'items': []})
    return evidence


def _weather_expectation(weather: dict) -> dict:
    """Descriptive attention to external change, NEVER a tomato risk labeler.

    Reuse the existing 0.5°C trend display tolerance. A moving external forecast
    adds a change to watch (raise); a flat/missing forecast makes no adjustment.
    Cooling is NOT assumed safe; no automatic lower/override of MODEL_OUTPUT.
    """
    result = {'weather_expectation': 'unknown', 'attention_adjustment': 'none',
              'adjustment_reason': '没有可采用的未来天气证据，不调整关注程度。'}
    if weather['status'] != 'ok':
        return result
    points = weather['result']['items']
    first, last = points[0], points[-1]
    delta = last['temperature'] - first['temperature']
    moving = abs(delta) > TREND_TOLERANCES['temperature']
    result['weather_expectation'] = ('warming' if delta > 0 else 'cooling') if moving else 'unknown'
    result['attention_adjustment'] = 'raise' if moving else 'none'
    result['adjustment_reason'] = (
        f"外部天气预报（{weather['provider']}）：{first['timestamp']}温度{first['temperature']}°C，"
        f"至{last['timestamp']}为{last['temperature']}°C（首尾变化{delta:+.2f}°C；"
        f"区间最低{min(p['temperature'] for p in points)}°C、最高{max(p['temperature'] for p in points)}°C）。"
        + ('增加对外部升降温变化的关注；不能据此推断内部同步变化或番茄风险等级上升。' if moving else
           '首尾变化未超过已有0.5°C趋势显示容差，不调整关注程度；unknown不等于天气无风险。')
        + '保留原始模型标签和概率，不因天气改判。')
    return result


def _knowledge(current, enabled, trace, anchor):
    evidence = normalize_evidence('KNOWLEDGE', 'LOCAL_KNOWLEDGE', datetime.now(timezone.utc).isoformat(),
                                  'unavailable', {'items': []}, '本次未启用知识检索。', citation=[])
    if not enabled:
        return normalize_evidence('KNOWLEDGE', 'LOCAL_KNOWLEDGE', anchor.isoformat(),
                                  'unavailable', None, '本次分析未启用知识库（include_knowledge=false）')
    query = knowledge_query(current, ANALYSIS_QUESTION)
    try:
        # The registered B05 function executes for real. analysis never imports rag.
        tool = TOOL_FUNCTIONS['search_plant_knowledge'](query=query)
    except Exception as error:
        tool = {'status': 'error', 'source': 'LOCAL_KNOWLEDGE', 'time': datetime.now(timezone.utc).isoformat(),
                'data': {}, 'error': f'知识工具执行失败（{type(error).__name__}）。'}
    trace.append({'tool': 'search_plant_knowledge', 'status': tool['status'], 'adopted': False,
                  'adopt_reason': '尚未完成引用与相关性校验。', 'arguments': {'query': query}, 'source_type': 'KNOWLEDGE'})
    items = valid_knowledge_items(tool.get('data', {}).get('items')) if tool['status'] == 'ok' else []
    evidence.update(source=tool.get('source'), time=tool.get('time'), status=tool['status'],
                    result={'query': query, 'items': items}, citation=[i['citation'] for i in items], error=tool.get('error'))
    if evidence['status'] == 'ok':
        try:
            if not evidence['source'] or datetime.fromisoformat(evidence['time']).tzinfo is None:
                raise ValueError('missing evidence identity')
        except (ValueError, TypeError):
            evidence.update(status='error', result={'query': query, 'items': []}, citation=[], error='知识工具缺少有效来源或带时区的获取时间，未采用。')
    return evidence


async def run_analysis(analysis_time=None, location='北京', include_weather: bool = False, include_knowledge: bool = False) -> dict:
    anchor = normalize_time(analysis_time)
    if not isinstance(location, str) or not location.strip() or len(location.strip()) > 100:
        raise ValueError('location 必须是1至100字的地点名称。')
    location = location.strip()
    tool_trace = []
    current = deepcopy(get_current_environment())
    tool_trace.append({'tool': 'get_current_environment', 'status': current['status'], 'adopted': False,
                       'adopt_reason': '尚未完成锚点校验。', 'arguments': {}, 'source_type': 'CURRENT_STATE'})
    if current['status'] == 'ok':
        try:
            if any(type(current['data'].get(key)) not in (int, float) or not math.isfinite(current['data'][key]) for key in TREND_TOLERANCES):
                raise ValueError('invalid current values')
            if _moment(current['data']['timestamp']) > anchor:
                current.update(status='unavailable', data={}, error='B02当前快照晚于分析锚点，不能当作该时刻的当前状态。')
        except (KeyError, TypeError, ValueError):
            current.update(status='unavailable', data={}, error='B02当前快照缺少有效时间戳。')
    # Tool retrieval time is distinct from the as-of anchor / original state timestamp.
    current['analysis_time'] = anchor.isoformat()
    history = await to_thread(_history, anchor)
    prediction = await to_thread(predict_window, history['items'] if history['status'] == 'ok' else [])
    prediction['analysis_time'] = anchor.isoformat()
    weather = await to_thread(_weather, anchor, location, include_weather, tool_trace)
    knowledge = await to_thread(_knowledge, current, include_knowledge, tool_trace, anchor)
    statuses = {'current_state': 'ok' if current['status'] == 'ok' else 'unavailable',
                'recent_history': history['status'], 'prediction': prediction['status'],
                'weather': weather['status'], 'plant_knowledge': knowledge['status'], 'knowledge': knowledge['status']}
    limits = [
        '本链只使用B02当前快照、锚点前3小时历史和B06已保存模型；未查询外部天气或植物知识。地点仅作档案标识。',
        '无土壤湿度、无独立天气预报和番茄生长阶段证据，不能判断是否需要浇水，也不能引用未提供的番茄适宜阈值。',
        'SIMULATED是模拟数据；attention_v1仅在SIMULATED与RULE_v1上训练，MODEL_OUTPUT不能替代实际观测，概率未经校准。',
        '预测从实际输入末点开始，不从请求时间平移；WATCH必须如实保留，不等于已经发生异常或番茄病害。',
        '当前状态是B02最后保存的快照，不保证与历史末点同步；按各自timestamp核对。',
    ]
    if include_weather:
        limits[0] = '本链使用B02当前快照、锚点前3小时历史、B06已保存模型，并通过原有工具获取可选外部天气；未查询植物知识。'
        limits[1] = '无土壤湿度和番茄生长阶段证据，不能判断是否需要浇水，也不能引用未提供的番茄适宜阈值。'
        limits.append('天气是地点的外部预报，不是内部实测；工具只提供温度与湿度，不能据此推断降雨、光照或温室内变化。外部趋势关注调整不是新增风险等级，也不修改MODEL_OUTPUT。')
        limits.append('retrieved_at是本次获取时间，forecast_time是预报有效时间；若回查过去锚点，本次获取的预报不代表当时可得的历史预报。天气区间与模型未来1小时区间可能不同，不能混称。')
        if weather['status'] != 'ok':
            limits.append('外部天气证据未采用：' + (weather['error'] or '不可用。'))
    if include_knowledge:
        limits[0] = '本链使用当前状态、锚点前3小时历史、已保存B06模型和通过B05注册工具实际检索的可选知识；天气是否采用以证据列表为准。'
        limits[1] = '知识是条件性养护背景，不是内部实测或未来预报。无土壤湿度、品种和生育期，不能决定浇水或诊断伤害。'
    trend = _trend(history)
    evidence_by_type = standardize(current, history, prediction, weather, knowledge, anchor, trend)
    evidence_records = []
    adopted_records = []
    decisions = {}
    for evidence in evidence_by_type:
        adopted, reason = adoption(evidence)
        decisions[evidence['source_type']] = (adopted, reason)
        if adopted:
            adopted_records.append(deepcopy(evidence))
        # Disabled sources remain in the archive, but never enter judgment inputs.
        disabled = (evidence['source_type'] == 'KNOWLEDGE' and not include_knowledge
                    or evidence['source_type'] == 'WEATHER_FORECAST' and not include_weather)
        if adopted or disabled:
            evidence_records.append(deepcopy(evidence))
    for call in tool_trace:
        call['adopted'], call['adopt_reason'] = decisions[call['source_type']]
    if not decisions['KNOWLEDGE'][0]:
        limits.append('本次无可采用知识：' + decisions['KNOWLEDGE'][1])
    conflicts, conclusion_level = assess_conflicts(adopted_records, trend, _weather_expectation(weather)['weather_expectation'])
    limits.append('supported只表示现有证据支持各自范围内的描述；不代表未来结果确定。conflicting保留未消解分歧；insufficient表示核心证据不足。')
    for label, evidence in [('当前状态', current), ('近3小时历史', history), ('预测', prediction)]:
        if evidence['status'] != 'ok':
            limits.append(label + '证据缺失：' + (evidence.get('error') or '不可用。'))
    judgment = {'analysis_time': anchor.isoformat(), 'location': location,
                'current_state': current['data'] if current['status'] == 'ok' else None,
                'history_window': {key: history[key] for key in ('start', 'end', 'interval', 'hours', 'count', 'source')},
                'recent_trend': trend,
                'predicted_attention': deepcopy(prediction), 'evidence_status': statuses,
                'weather_evidence': weather, 'knowledge': knowledge,
                'evidence_by_type': evidence_by_type, 'evidence_records': evidence_records,
                'tool_trace': deepcopy(tool_trace), 'conflicts': conflicts, 'conclusion_level': conclusion_level,
                **_weather_expectation(weather),
                'judgment_limits': limits, 'generated_by': 'PROGRAM',
                'explanation_status': 'unavailable', 'llm_error': None}
    record = {'run_id': 'run_' + anchor.strftime('%Y%m%d_%H%M%S') + '_' + uuid4().hex[:12],
              'analysis_time': anchor.isoformat(), 'location': location, 'question': ANALYSIS_QUESTION,
              'state': current, 'history_window': history, 'prediction': prediction,
              'judgment': judgment, 'answer': '', 'evidence_status': statuses,
              'created_at': datetime.now(timezone.utc).isoformat(), 'tool_trace': tool_trace}
    # Save immutable snapshots BEFORE the network request so a failed explanation
    # cannot discard the run_id/evidence. Only answer + explanation metadata finish later.
    db.add_analysis_run(record)
    try:
        for attempt in range(2):
            answer = await explain_analysis(ANALYSIS_QUESTION, deepcopy(judgment))
            issue = explanation_issue(answer, judgment)
            if issue is None:
                record['answer'] = answer
                judgment['explanation_status'] = 'ok'
                break
            if attempt == 1:
                judgment['llm_error'] = {'type': 'EXPLANATION_REJECTED', 'message': issue + '结构化判断和证据已保存。'}
    except (OpenAIError, MissingAPIKeyError, EmptyAnswerError) as error:
        # No substituted "LLM answer": the program evidence remains accessible.
        judgment['llm_error'] = error_details(error, 'LLM解释暂不可用；结构化判断和原始证据已保存，可按run_id回查。')
    db.finish_analysis_run(record['run_id'], record['answer'], judgment)
    return record
