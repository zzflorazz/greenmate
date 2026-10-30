"""Controlled replacement of simulated history; uses S1 analysis unchanged."""
import sqlite3
from contextlib import closing
from datetime import datetime, timedelta, timezone

import db
import state
from analysis import ANALYSIS_QUESTION, normalize_time
from ml_dataset import _moment, INTERVAL

SCENARIOS = {
    'S1_stable': [29.8, 29.9, 29.8, 30.0, 29.9, 30.0],
    'S2_ramp': [25.0, 26.0, 27.0, 28.0, 29.0, 30.0],
    'S4_conflict': [27.0, 28.0, 29.0, 30.0, 31.0, 32.0],
}
MANAGED_NAMES = ('S1_stable', 'S2_ramp', 's1_stable', 'S4_conflict')


def _anchor(analysis_time):
    if analysis_time is not None:
        return normalize_time(analysis_time)
    now = datetime.now(timezone.utc)
    # Reuse the active simulation's anchor across both buttons and retries.
    # This makes repeated applications stable rather than appending shifted copies.
    with closing(sqlite3.connect(db._database_path())) as connection:
        row = connection.execute("""
            SELECT timestamp FROM environment_samples
            WHERE source_type='SIMULATED' AND sim_scenario IN (?,?,?,?)
            ORDER BY julianday(timestamp) DESC, id DESC LIMIT 1
        """, MANAGED_NAMES).fetchone()
    if row is not None:
        latest = _moment(row[0])
        if timedelta(0) <= now-latest < INTERVAL:
            return latest
    return now


def apply_scenario(name, analysis_time=None) -> dict:
    if name not in SCENARIOS:
        raise ValueError('场景仅支持 S1_stable、S2_ramp 或 S4_conflict。')
    db.init_db()
    anchor = _anchor(analysis_time)
    rows = db.get_samples_at(anchor, 3)
    # Keep B05 seed_demo / real observations intact. Never mix two simulated
    # trajectories into the same window, and never rewrite existing run snapshots.
    if any(row['source_type'] != 'SIMULATED' or row['sim_scenario'] not in MANAGED_NAMES for row in rows):
        raise ValueError('该3小时窗口存在非场景演示样本，已保留原数据；请选择无冲突的分析时间。')
    expected = [{'timestamp': (anchor-INTERVAL*(5-index)).isoformat(),
                 'temperature': temperature, 'humidity': 65.0, 'light': (18000.0 + 1200 * index) if name == 'S4_conflict' else 12000.0,
                 'source_type': 'SIMULATED', 'sim_scenario': name}
                for index, temperature in enumerate(SCENARIOS[name])]
    keys = tuple(expected[0])
    identical = len(rows) == 6 and all(all(actual[key] == wanted[key] for key in keys) for actual, wanted in zip(rows, expected))
    current = {key: expected[-1][key] for key in ('temperature', 'humidity', 'light', 'source_type', 'timestamp')}
    with closing(sqlite3.connect(db._database_path())) as connection, connection:
        if not identical:
            connection.executemany('DELETE FROM environment_samples WHERE id=?', [(row['id'],) for row in rows])
            connection.executemany('''INSERT INTO environment_samples
                (timestamp, temperature, humidity, light, source_type, sim_scenario)
                VALUES (?, ?, ?, ?, ?, ?)''', [db._sample_values(row) for row in expected])
        # A simulated clock: the B02 snapshot represents the scenario's final point,
        # not the time taken by a network call. Identical timestamp for both runs.
        connection.execute('''INSERT INTO current_state
            (id, temperature, humidity, light, source_type, timestamp)
            VALUES (1,:temperature,:humidity,:light,:source_type,:timestamp)
            ON CONFLICT(id) DO UPDATE SET temperature=excluded.temperature,
            humidity=excluded.humidity,light=excluded.light,source_type=excluded.source_type,
            timestamp=excluded.timestamp''', current)
    state.load_state()  # Refresh the existing B02 cache, without changing its code.
    return {'name': name, 'analysis_time': anchor.isoformat(), 'samples_written': 0 if identical else 6,
            'samples_removed': 0 if identical else len(rows), 'sample_count': 6,
            'current_state': state.get_state(), 'idempotent_reuse': identical,
            'note': '只替换选定窗口内的受管SIMULATED场景；旧analysis_runs与原seed_demo不改。'}


def _current(run):
    item = run['judgment']['current_state'] or {}
    return {key: item.get(key) for key in ('temperature', 'humidity', 'light', 'source_type')}


def _trends(run):
    return run['judgment']['recent_trend'].get('metrics', {})


def _prediction(run):
    return {key: run['prediction'].get(key) for key in ('status', 'prediction', 'probability', 'probability_of', 'model_version', 'evidence_type', 'input_features')}


def _summary(run):
    return {'generated_by': run['judgment']['generated_by'], 'current': _current(run),
            'recent_trend': {key: {'direction': value['direction'], 'first': value['first'], 'last': value['last'], 'delta': value['delta']}
                             for key, value in _trends(run).items()},
            'predicted_attention': _prediction(run), 'judgment_limits': run['judgment']['judgment_limits']}


def _semantic_fields(run):
    fields = {'question': run['question'], 'analysis_time': run['analysis_time'], 'location': run['location'],
              'evidence_status': run['evidence_status'], 'judgment_limits': run['judgment']['judgment_limits'],
              'generated_by': run['judgment']['generated_by']}
    fields.update({'current.'+key: value for key,value in _current(run).items()})
    for metric, values in _trends(run).items():
        for key, value in values.items():
            fields[f'recent_trend.{metric}.{key}'] = value
    for key, value in _prediction(run).items():
        if key == 'input_features' and isinstance(value, dict):
            fields.update({'prediction.input_features.'+feature: number for feature,number in value.items()})
        else:
            fields['prediction.'+key] = value
    return fields


def compare_runs(run_a: str, run_b: str) -> dict:
    a, b = db.get_analysis_run(run_a), db.get_analysis_run(run_b)
    if a is None or b is None:
        raise LookupError('未找到对照档案，请检查两个run_id。')
    fields_a, fields_b = _semantic_fields(a), _semantic_fields(b)
    changed, unchanged = [], []
    for key in sorted(fields_a.keys() | fields_b.keys()):
        va, vb = fields_a.get(key), fields_b.get(key)
        if va == vb:
            unchanged.append({'field': key, 'value': va})
        else:
            changed.append({'field': key, 'run_a': va, 'run_b': vb})
    answer_a = a['answer'].strip().split('\n\n')[0] if a['answer'].strip() else None
    answer_b = b['answer'].strip().split('\n\n')[0] if b['answer'].strip() else None
    pairs = [('Current',_current(a),_current(b)),('Recent trend',_trends(a),_trends(b)),
             ('Predicted attention',_prediction(a),_prediction(b)),('Structured judgment',_summary(a),_summary(b)),
             ('Evidence status',a['evidence_status'],b['evidence_status']),('Answer 首段',answer_a,answer_b)]
    coverage = {}
    for key,run in [('run_a',a),('run_b',b)]:
        points = run['history_window']['items']
        coverage[key] = {'analysis_time':run['analysis_time'], 'history_start':run['history_window']['start'],
                         'history_end':run['history_window']['end'], 'count':len(points),
                         'temperatures':[point['temperature'] for point in points],
                         'first_timestamp':points[0]['timestamp'] if points else None,
                         'last_timestamp':points[-1]['timestamp'] if points else None}
    notes = ['只比较已归档快照，没有重新分析、改提示词、改模型或增加证据。',
             'structured_delta排除run_id、样本ID、取证/创建时刻和LLM措辞等非业务差异；完整原值仍可按run_id回查。']
    substantive = [item for item in changed if item['field'] not in ('analysis_time', 'location')]
    if not substantive:
        notes.append('结构化字段完全一致：请核对下方窗口温度序列是否覆盖升温段，不能仅凭不同场景名认定过程已改变。')
    else:
        notes.append('结构化差异见changed；当前值相近并不表示历史均值、delta及趋势方向相同。')
    if a['prediction'].get('status') != 'ok' or b['prediction'].get('status') != 'ok':
        notes.append('至少一次预测不可用，不能据此比较模型关注程度；请核对历史窗口和预测状态。')
    elif a['prediction'].get('prediction') == b['prediction'].get('prediction'):
        notes.append('两次模型标签相同也如实保留；同时核对P(WATCH)与输入特征。升温不必然使此合成数据模型提高风险概率，不能手工改为WATCH。')
    if a['analysis_time'] != b['analysis_time']:
        notes.append('两次时间锚点不同，本次不是严格同时间的过程对照。')
    return {'run_a':run_a,'run_b':run_b,'same_question':a['question']==b['question'],
            'question':a['question'] if a['question']==b['question'] else {'run_a':a['question'],'run_b':b['question']},
            'fixed_question_match':a['question']==b['question']==ANALYSIS_QUESTION,
            'same_analysis_time':a['analysis_time']==b['analysis_time'],
            'rows':[{'field':field,'run_a':va,'run_b':vb,'changed':va!=vb} for field,va,vb in pairs],
            'structured_delta':{'changed':changed,'unchanged':unchanged}, 'window_coverage':coverage,
            'evidence_records': {'run_a': a['judgment'].get('evidence_records', []),
                                 'run_b': b['judgment'].get('evidence_records', [])},
            'notes':notes}
