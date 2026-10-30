"""B06: reproducible time-window datasets; no model training or scaling."""
import argparse
import json
import math
import sqlite3
from collections import Counter
from contextlib import closing
from datetime import datetime, timedelta, timezone
from pathlib import Path

import db

CONFIG_PATH = Path(__file__).with_name('dataset_config.json')
FEATURE_NAMES = ['temp_current', 'temp_mean', 'temp_delta', 'hum_current',
                 'hum_mean', 'hum_delta', 'light_current', 'light_delta']
LABEL_RULES = {
    'name': 'next_window_attention', 'label_source': 'RULE_v1',
    'aggregation': 'future_window_mean', 'operator': 'any',
    'temperature': {'watch_gte': 32, 'watch_lte': 10, 'unit': '°C'},
    'humidity': {'watch_lte': 35, 'watch_gte': 85, 'unit': '%'},
    'light': {'watch_gte': 20000, 'watch_lte': 800, 'unit': 'lux'},
    'otherwise': 'NORMAL',
}
INTERVAL = timedelta(minutes=30)


def load_samples() -> list[dict]:
    """Read all original rows, including IDs; never use the rolling 24h query."""
    with closing(sqlite3.connect(db._database_path())) as connection:
        connection.row_factory = sqlite3.Row
        rows = connection.execute('SELECT * FROM environment_samples ORDER BY julianday(timestamp) ASC, id ASC').fetchall()
    return [dict(row) for row in rows]


def _moment(value: str) -> datetime:
    moment = datetime.fromisoformat(value)
    if moment.tzinfo is None:
        raise ValueError('原始 timestamp 必须带时区')
    return moment.astimezone(timezone.utc)


def _features(window: list[dict]) -> dict:
    # Only input-window measurements enter X. No future values or metadata.
    temperatures = [row['temperature'] for row in window]
    humidities = [row['humidity'] for row in window]
    return dict(zip(FEATURE_NAMES, [
        temperatures[-1], sum(temperatures) / len(window), temperatures[-1] - temperatures[0],
        humidities[-1], sum(humidities) / len(window), humidities[-1] - humidities[0],
        window[-1]['light'], window[-1]['light'] - window[0]['light'],
    ]))


def _label(future: list[dict]) -> str:
    # RULE_v1 / next_window_attention: WATCH if ANY future-window mean is
    # temperature >=32 or <=10 °C; humidity <=35 or >=85%; light >=20000 or
    # <=800 lux. Otherwise NORMAL. Future measurements are used ONLY for y.
    temperature, humidity, light = [sum(row[key] for row in future) / len(future)
                                    for key in ('temperature', 'humidity', 'light')]
    watch = temperature >= 32 or temperature <= 10 or humidity <= 35 or humidity >= 85 or light >= 20000 or light <= 800
    return 'WATCH' if watch else 'NORMAL'


def _construct(samples: list[dict], window_size: int, horizon: int) -> tuple[list[dict], dict]:
    if any(type(value) is not int or value <= 0 for value in (window_size, horizon)):
        raise ValueError('window_size 和 horizon 必须是正整数')
    ordered = sorted(samples, key=lambda row: (_moment(row['timestamp']), row['id']))
    start = _moment(ordered[0]['timestamp']) if ordered else None
    split = start + timedelta(days=5) if start else None
    end = start + timedelta(days=7) if start else None
    # Split ORIGINAL observations before window construction. Both the input and
    # target must fit inside the same partition; never split overlapping windows.
    partitions = {'train': [], 'test': []}
    for row in ordered:
        timestamp = _moment(row['timestamp'])
        if start <= timestamp < split:
            partitions['train'].append(row)
        elif split <= timestamp < end:
            partitions['test'].append(row)
    result = []
    for name, rows in partitions.items():
        for offset in range(len(rows) - window_size - horizon + 1):
            segment = rows[offset:offset + window_size + horizon]
            times = [_moment(row['timestamp']) for row in segment]
            if any(right - left != INTERVAL for left, right in zip(times, times[1:])):
                continue  # Missing points, duplicates or irregular spacing invalidate this window.
            if any(row['source_type'] != 'SIMULATED' or any(
                type(row[key]) not in (int, float) or not math.isfinite(row[key])
                for key in ('temperature', 'humidity', 'light')) for row in segment):
                continue  # B03 weather and invalid measurements cannot enter this dataset.
            window, future = segment[:window_size], segment[window_size:]
            result.append({
                'sample_id': f"w{window_size}-h{horizon}:" + ','.join(str(row['id']) for row in segment),
                'split': name,
                'window_start': times[0].isoformat(), 'window_end': times[window_size - 1].isoformat(),
                'future_start': times[window_size].isoformat(), 'future_end': times[-1].isoformat(),
                'input_sample_ids': [row['id'] for row in window],
                'input_timestamps': [row['timestamp'] for row in window],
                'future_sample_ids': [row['id'] for row in future],
                'features': _features(window), 'label': _label(future), 'label_source': 'RULE_v1',
            })
    config = {
        'window_size': window_size, 'horizon': horizon, 'sample_interval_minutes': 30,
        'features': FEATURE_NAMES, 'label_rules': LABEL_RULES, 'label_source': 'RULE_v1',
        'allowed_source_types': ['SIMULATED'],
        'dataset_start': start.isoformat() if start else None,
        'split_time': split.isoformat() if split else None,
        'dataset_end_exclusive': end.isoformat() if end else None,
        'split_policy': 'first_5_days_train_next_2_days_test; split_raw_rows_before_windows',
        'original_row_count': len(ordered),
    }
    return result, config


def build_windows(window_size=6, horizon=2) -> list[dict]:
    """Return traceable train/test examples; cross-boundary windows are excluded."""
    return _construct(load_samples(), window_size, horizon)[0]


def _summary(windows: list[dict], config: dict) -> dict:
    result = {'window_size': config['window_size'], 'horizon': config['horizon'],
              'feature_names': config['features'], 'label_source': 'RULE_v1',
              'split_time': config['split_time'], 'original_row_count': config['original_row_count']}
    for name in ('train', 'test'):
        rows = [row for row in windows if row['split'] == name]
        counts = Counter(row['label'] for row in rows)
        result[name] = {
            'count': len(rows), 'class_distribution': {label: counts[label] for label in ('NORMAL', 'WATCH')},
            'time_range': {'start': rows[0]['window_start'] if rows else None,
                           'end': rows[-1]['future_end'] if rows else None},
        }
    return result


def dataset_summary() -> dict:
    # GET is read-only; follow the last explicitly generated configuration.
    config = json.loads(CONFIG_PATH.read_text(encoding='utf-8')) if CONFIG_PATH.exists() else {}
    windows, current = _construct(load_samples(), config.get('window_size', 6), config.get('horizon', 2))
    return _summary(windows, current)


def generate_dataset(window_size=6, horizon=2) -> dict:
    windows, config = _construct(load_samples(), window_size, horizon)
    CONFIG_PATH.write_text(json.dumps(config, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    return _summary(windows, config)


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--window-size', type=int, default=6)
    parser.add_argument('--horizon', type=int, default=2)
    arguments = parser.parse_args()
    print(json.dumps(generate_dataset(arguments.window_size, arguments.horizon), ensure_ascii=False, indent=2))
