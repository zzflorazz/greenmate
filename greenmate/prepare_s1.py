"""Explicit S1 preparation: reuse a suitable recent segment or append six calm points.

Never edits/deletes B05 seed_demo rows, inserts future evidence, or changes model
files. Analysis itself never calls this script or generates its own evidence.
"""
import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

import db
import state
from analysis import _history, normalize_time

PREPARATION_PATH = Path(__file__).with_name('s1_preparation.json')


def prepare_s1() -> dict:
    db.init_db()
    state.load_state()
    anchor = normalize_time()
    history = _history(anchor)
    rows = history['items']
    calm = not rows or (all(row['source_type'] == 'SIMULATED' and 29 <= row['temperature'] <= 30 for row in rows)
                        and max(row['temperature'] for row in rows)-min(row['temperature'] for row in rows) <= 0.5
                        and max(row['humidity'] for row in rows)-min(row['humidity'] for row in rows) <= 2)
    suitable = history['status'] == 'ok' and calm
    if not suitable:
        if not calm:
            raise ValueError('最近3小时已有非S1稳定样本，不能为制造稳定场景覆盖或混入数据。请保留原记录，在无重叠时间段再准备S1。')
        from ml_dataset import _moment, INTERVAL
        if rows:
            # Complete only an already calm, aligned simulation, never hide an
            # existing non-calm observation or shift any original timestamp.
            latest = _moment(rows[-1]['timestamp'])
            end = latest + ((anchor-latest)//INTERVAL)*INTERVAL
        else:
            end = anchor
        target_times = [end-timedelta(minutes=30*(5-index)) for index in range(6)]
        existing = {_moment(row['timestamp']): row for row in rows}
        if len(existing) != len(rows) or any(moment not in target_times for moment in existing):
            raise ValueError('已有样本时间不在连续半小时网格上；不能覆盖或用旧数据拼凑S1。')
        temperatures = [29.5, 29.6, 29.4, 29.5, 29.6, 29.5]
        humidities = [65.0, 65.3, 64.9, 65.1, 65.2, 65.0]
        base_temperature = sum(row['temperature'] for row in rows)/len(rows) if rows else None
        base_humidity = sum(row['humidity'] for row in rows)/len(rows) if rows else None
        base_light = sum(row['light'] for row in rows)/len(rows) if rows else 12000.0
        for index, moment in enumerate(target_times):
            if moment in existing:
                continue
            sample = {'timestamp': moment.isoformat(),
                      'temperature': temperatures[index] if base_temperature is None else base_temperature,
                      'humidity': humidities[index] if base_humidity is None else base_humidity,
                      'light': base_light, 'source_type': 'SIMULATED', 'sim_scenario': 's1_stable'}
            db.add_sample(sample)
        rows = db.get_samples_at(anchor, 3)
        mode = 'completed_existing_stable_segment' if existing else 'generated_s1_stable'
    else:
        mode = 'reused_existing_stable_segment'
    # Reuse B02's update function; do not rewrite its timestamp or persistence logic.
    latest = rows[-1]
    if latest['source_type'] == 'SIMULATED':
        state.update_state({key: latest[key] for key in ('temperature', 'humidity', 'light')}, source_type='SIMULATED')
    anchor = datetime.now(timezone.utc)  # After the B02 snapshot's true save time.
    result = {'mode': mode, 'analysis_time': anchor.isoformat(), 'location': '北京',
              'history_start': (anchor-timedelta(hours=3)).isoformat(), 'history_end': anchor.isoformat(),
              'sample_count': len(rows), 'source_type': 'SIMULATED',
              'note': '只准备稳定模拟段；不训练、不调整WATCH/NORMAL。旧样本保留。'}
    PREPARATION_PATH.write_text(json.dumps(result, ensure_ascii=False, indent=2)+'\n', encoding='utf-8')
    return result


if __name__ == '__main__':
    try:
        print(json.dumps(prepare_s1(), ensure_ascii=False, indent=2))
    except ValueError as error:
        raise SystemExit(str(error)) from None
