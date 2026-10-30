"""Load the persisted v1 model and infer from the newest complete input window.

No training, interpolation, backward search for an older usable window, or writes
are performed here. probability always means P(WATCH), not confidence in truth.
"""
import hashlib
import json
import math
from pathlib import Path

import joblib
from sklearn.utils.validation import check_is_fitted

import ml_dataset as dataset

MODELS_DIR = Path(__file__).with_name('models')
MODEL_VERSION = 'attention_v1'


def load_model() -> dict:
    manifest = json.loads((MODELS_DIR / f'{MODEL_VERSION}_manifest.json').read_text(encoding='utf-8'))
    if manifest.get('feature_names') != dataset.FEATURE_NAMES:
        raise ValueError('manifest feature_names 与 FEATURE_NAMES 顺序不一致，拒绝加载。')
    if manifest.get('model_version') != MODEL_VERSION:
        raise ValueError('manifest 模型版本不匹配。')
    path = MODELS_DIR / f'{MODEL_VERSION}.joblib'
    if hashlib.sha256(path.read_bytes()).hexdigest() != manifest.get('artifact_sha256'):
        raise ValueError('模型文件与 manifest 校验摘要不一致。')
    payload = joblib.load(path)
    required = {'model', 'scaler', 'feature_names', 'window_config', 'model_version', 'label_map'}
    if not isinstance(payload, dict) or not required <= payload.keys():
        raise ValueError('模型包缺少 model/scaler/feature_names/window_config 等必需内容。')
    if payload['feature_names'] != dataset.FEATURE_NAMES or payload['model_version'] != MODEL_VERSION:
        raise ValueError('模型包特征顺序或版本不匹配。')
    config = payload['window_config']
    if config != manifest.get('window_config') or any(
        type(config.get(key)) is not int or config[key] <= 0 for key in ('window_size', 'horizon')
    ) or config.get('window_size') != manifest.get('window_size') or config.get('horizon') != manifest.get('horizon'):
        raise ValueError('模型与 manifest 窗口配置不匹配。')
    if config.get('features') != dataset.FEATURE_NAMES or config.get('sample_interval_minutes') != 30:
        raise ValueError('模型窗口特征或采样间隔不匹配。')
    if payload['label_map'] != {'0': 'NORMAL', '1': 'WATCH'} or payload['label_map'] != manifest.get('label_map'):
        raise ValueError('模型标签映射不匹配。')
    for estimator in (payload['model'], payload['scaler']):
        check_is_fitted(estimator)
        if estimator.n_features_in_ != len(dataset.FEATURE_NAMES):
            raise ValueError('模型或 scaler 特征维数不匹配。')
    if list(payload['model'].classes_) != [0, 1]:
        raise ValueError('模型类别不匹配。')
    return {**payload, 'manifest': manifest}


def predict_window(rows: list[dict] | None = None) -> dict:
    result = {'status': 'unavailable', 'prediction': None, 'probability': None,
              'model_version': MODEL_VERSION, 'window_start': None, 'window_end': None,
              'source_type': 'UNKNOWN', 'evidence_type': 'MODEL_OUTPUT'}
    try:
        payload = load_model()
    except Exception as error:
        return {**result, 'error': f'模型加载或契约校验失败：{type(error).__name__}: {error}'}
    config = payload['window_config']
    size = config['window_size']
    try:
        # Read the newest raw rows BEFORE source/value filtering. A bad newest
        # point invalidates this window; never retrieve an older good window.
        rows = (dataset.load_samples() if rows is None else rows)[-size:]
        if len(rows) < size:
            return {**result, 'error': f'历史样本不足{size}个，无法预测。'}
        times = [dataset._moment(row['timestamp']) for row in rows]
        result.update(window_start=times[0].isoformat(), window_end=times[-1].isoformat())
        sources = {row['source_type'] for row in rows}
        result['source_type'] = next(iter(sources)) if len(sources) == 1 else 'MIXED'
        if any(right - left != dataset.INTERVAL for left, right in zip(times, times[1:])):
            return {**result, 'error': '最新窗口时间不连续（要求每30分钟一个点），不回退到旧窗口。'}
        if sources != {'SIMULATED'}:
            return {**result, 'error': 'attention_v1 仅在 SIMULATED 样本上训练，当前窗口来源不适用。'}
        if any(type(row[key]) not in (int, float) or not math.isfinite(row[key])
               for row in rows for key in ('temperature', 'humidity', 'light')):
            return {**result, 'error': '最新窗口存在缺失或无效数值，不使用旧数据补齐。'}
        features = dataset._features(rows)  # Exactly the training feature implementation.
        vector = [[features[name] for name in payload['feature_names']]]
        scaled = payload['scaler'].transform(vector)  # NO fit/fit_transform here.
        probability = float(payload['model'].predict_proba(scaled)[0, 1])
        prediction = payload['label_map'][str(int(payload['model'].predict(scaled)[0]))]
        if not math.isfinite(probability) or not 0 <= probability <= 1:
            raise ValueError('模型返回无效概率')
        return {**result, 'status': 'ok', 'prediction': prediction, 'probability': probability,
                'error': None, 'probability_of': 'WATCH', 'horizon': config['horizon'],
                'input_features': features, 'input_sample_ids': [row.get('id') for row in rows],
                'model_artifact_sha256': payload['manifest']['artifact_sha256'],
                'model_trained_at': payload['manifest']['trained_at'],
                'target_start': times[-1].isoformat(),
                'target_end': (times[-1] + config['horizon'] * dataset.INTERVAL).isoformat(),
                'horizon_minutes': config['horizon'] * 30,
                'limitations': '仅基于SIMULATED合成数据与RULE_v1规则标签；概率未经校准，不保证未来真实风险。预测起点是window_end，不是请求时刻；需另查历史、天气与养护知识。'}
    except Exception as error:
        return {**result, 'error': f'最新窗口推理不可用：{type(error).__name__}: {error}'}


def predict_latest() -> dict:
    return predict_window()
