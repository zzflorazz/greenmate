"""S4 evidence identity, adoption policy, cross-scope disagreements and output guard.

Transport success is NOT adoption. Keep unavailable/error records for diagnostics,
while disabled-source entries in evidence_records are archival placeholders only.
"""
from copy import deepcopy
from datetime import datetime, timezone
import json
import math
import re

SOURCE_TYPES = ('CURRENT_STATE', 'HISTORY', 'MODEL_OUTPUT', 'WEATHER_FORECAST', 'KNOWLEDGE')


def normalize_evidence(source_type, source, time, status, result=None, error=None, **extensions):
    if source_type not in SOURCE_TYPES or status not in ('ok', 'unavailable', 'error'):
        raise ValueError('无效证据类型或状态。')
    return deepcopy(dict(source_type=source_type, source=source, time=time, status=status,
                         result=result, error=error, **extensions))


def knowledge_query(current, question):
    state = current.get('data') if current.get('status') == 'ok' else None
    context = ('当前状态缺失' if not state else
               f"当前温度{state['temperature']}°C，空气湿度{state['humidity']}%，光照{state['light']}lux；来源{current['source']}")
    return f'{question} 当前状态：{context}。检索番茄适宜温度、湿度、光照、高温风险和关注条件。'


def valid_knowledge_items(items):
    if not isinstance(items, list):
        return []
    valid = []
    for item in items:
        if not isinstance(item, dict) or item.get('name') != '番茄':
            continue
        citation = item.get('citation', {})
        if not isinstance(citation, dict):
            continue
        if (not all(isinstance(citation.get(k), str) and citation[k].strip() for k in ('id', 'name', 'snippet'))
                or citation['name'] != item['name'] or citation['id'] != item.get('id')):
            continue
        # Each quoted line must be present verbatim in the returned knowledge.
        texts = [value for key, value in item.items() if key != 'citation' and isinstance(value, str)]
        if all(any(line in text for text in texts) for line in citation['snippet'].splitlines() if line.strip()):
            valid.append(deepcopy(item))
    return valid


def standardize(current, history, prediction, weather, knowledge, anchor, trend):
    return [
        normalize_evidence('CURRENT_STATE', current.get('source'), current.get('data', {}).get('timestamp') or current.get('time'),
                           current['status'], current.get('data'), current.get('error')),
        normalize_evidence('HISTORY', history['source'], history['end'], history['status'],
                           {**{k: history[k] for k in ('start', 'end', 'interval', 'hours', 'count', 'items')}, 'trend': trend}, history.get('error')),
        normalize_evidence('MODEL_OUTPUT', 'MODEL_OUTPUT', prediction.get('window_end') or anchor.isoformat(), prediction['status'],
                           prediction, prediction.get('error'), model_version=prediction.get('model_version')),
        deepcopy(weather), deepcopy(knowledge),
    ]


def adoption(record):
    if record['status'] != 'ok':
        return False, record.get('error') or '证据不可用。'
    if record['source_type'] == 'KNOWLEDGE' and not record['result'].get('items'):
        return False, '工具调用成功，但无带有效citation的番茄相关命中；未采用。'
    return True, {'CURRENT_STATE': '采用锚点之前的有效当前快照，只描述当前数值。',
                  'HISTORY': '采用连续3小时历史，用于描述内部近期变化。',
                  'MODEL_OUTPUT': '采用已保存模型的原始标签和概率，不作覆盖。',
                  'WEATHER_FORECAST': '只采用通过时间校验的未来预报，用于外部趋势描述。',
                  'KNOWLEDGE': '采用有稳定id、名称和原文片段的番茄知识，作为条件性养护背景。'}[record['source_type']]


def assess_conflicts(adopted, trend, weather_expectation):
    sources = {e['source_type']: e for e in adopted}
    conflicts = []
    direction = trend.get('metrics', {}).get('temperature', {}).get('direction')
    if 'HISTORY' in sources and 'WEATHER_FORECAST' in sources and (direction, weather_expectation) in (
            ('rising', 'cooling'), ('falling', 'warming')):
        conflicts.append({'between': ['HISTORY', 'WEATHER_FORECAST'], 'type': 'direction_conflict',
                          'description': f"内部近3小时温度{direction}，外部未来预报{weather_expectation}，变化方向不同。空间与时间窗口不同，不能相互抵消；尚缺内部后续实测与内外耦合信息。"})
    # NORMAL vs conditional heat concern is attention divergence, never proof that
    # either model/knowledge is false. No conflict is fabricated for WATCH.
    model = sources.get('MODEL_OUTPUT', {}).get('result', {})
    current = sources.get('CURRENT_STATE', {}).get('result') or {}
    knowledge = sources.get('KNOWLEDGE', {}).get('result', {}).get('items', [])
    for item in knowledge:
        threshold = item.get('heat_attention_c')
        if (model.get('prediction') == 'NORMAL' and type(threshold) in (int, float)
                and math.isfinite(threshold) and current.get('temperature', -math.inf) > threshold):
            conflicts.append({'between': ['MODEL_OUTPUT', 'KNOWLEDGE'], 'type': 'attention_divergence',
                              'description': f"模型原始输出NORMAL；知识{item['citation']['id']}给出的条件性高温管理参考为{threshold}°C，当前模拟温度{current['temperature']}°C高于该参考，仍值得核查。两者目标和适用范围不同，不改模型标签，不据此诊断伤害。"})
    level = 'conflicting' if conflicts else ('supported' if {'CURRENT_STATE', 'HISTORY', 'MODEL_OUTPUT'} <= sources.keys() else 'insufficient')
    return conflicts, level


# A program boundary, including negated statements: unsafe text is not published
# as a successful explanation. It is NOT silently rewritten into a fake LLM answer.
FORBIDDEN = re.compile(r'必然|一定|肯定会|保证(?:会|恶化|安全)|确定会|100%|百分之百')


def explanation_issue(answer, judgment):
    if re.search(r'\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d+)?(?![\d.])(?!(?:Z|[+-]\d{2}:\d{2}))', answer):
        return '解释引用ISO时间但省略时区，已阻止误标北京时间或UTC。'
    if FORBIDDEN.search(answer):
        return '解释含确定性用语，已阻止作为分析回答发布。'
    adopted = {e['source_type']: e for e in judgment['evidence_records'] if e['status'] == 'ok'}
    if judgment['conclusion_level'] == 'conflicting' and ('conflicting' not in answer or not any(w in answer for w in ('分歧', '冲突'))):
        return '解释未保留程序的conflicting结论和分歧。'
    if 'KNOWLEDGE' in adopted:
        ids = [c['id'] for c in adopted['KNOWLEDGE']['citation']]
        if not any(identifier in answer for identifier in ids):
            return '知识解释缺少本次采用条目的citation id。'
    else:
        claims = re.compile(r'(?:已|通过|根据|依据|查过|检索到|查询到|查阅了)[^。；\n]{0,18}(?:知识库|知识检索|番茄知识|植物知识)')
        if claims.search(answer):
            return '没有采用知识证据，却声称已检索或依据知识。'
    return None


async def explain_s4(question, judgment):
    # Reuse the same configured LLM and retry transport; preserve llm.py and
    # B06 artifacts byte-for-byte. The fixed question is passed unchanged.
    from llm import ANALYSIS_EXPLANATION_PROMPT, _generate_text
    rules = '''\nS4解释约束：仅使用evidence_records中status=ok的已采用证据；unavailable记录只说明未启用，不作为判断依据；tool_trace只表示实际调用及采纳关系。
区分模拟内部状态/历史、未经校准的MODEL_OUTPUT、户外未来预报与条件性知识；逐项说明各自支持什么，不能合并为单一恶化判断。
引用日期时间时保留完整ISO时区偏移；+00:00是UTC，不得标成北京时间；不转换、不省略时区。解释中写出程序给出的conclusion_level英文值。conflicts非空时说明方向/关注分歧及空间、时间、目标差异，说明仍缺内部后续实测、耦合信息和生育期。
知识被采用时须引用citation.id与name并解释命中片段；未采用时只说明未取得可采用知识，不声称查过资料。
不允许出现“必然”“一定”等确定性词，包括带否定前缀的表述。不得宣称当前链未执行的工具调用，不输出执行浇水等动作建议。'''
    provided = {k: v for k, v in judgment.items() if k not in ('explanation_status', 'llm_error')}
    return await _generate_text([
        {'role': 'system', 'content': ANALYSIS_EXPLANATION_PROMPT + rules},
        {'role': 'user', 'content': question + '\n\n程序生成的结构化判断：\n' + json.dumps(provided, ensure_ascii=False, allow_nan=False)},
    ])
