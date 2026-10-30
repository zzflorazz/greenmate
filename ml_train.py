"""B06 fixed-baseline evaluation and explicit attention_v1 persistence."""
import hashlib
import json
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
import joblib
import sklearn
from sklearn.dummy import DummyClassifier
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import accuracy_score, confusion_matrix, precision_score, recall_score, f1_score
from sklearn.preprocessing import StandardScaler

import ml_dataset as dataset
from ml_dataset import FEATURE_NAMES

METRICS_PATH = Path(__file__).with_name('ml_metrics.json')
RANDOM_STATE = 42
MODELS_DIR = Path(__file__).with_name('models')
MODEL_VERSION = 'attention_v1'


def _save_model(model, scaler, config, train_rows, report):
    MODELS_DIR.mkdir(exist_ok=True, parents=True)
    model_path = MODELS_DIR / f'{MODEL_VERSION}.joblib'
    payload = {'model': model, 'scaler': scaler, 'feature_names': list(FEATURE_NAMES),
               'window_config': config, 'model_version': MODEL_VERSION,
               'label_map': {'0': 'NORMAL', '1': 'WATCH'}}
    joblib.dump(payload, model_path)
    manifest = {
        'model_version': MODEL_VERSION, 'trained_at': report['generated_at'],
        'feature_names': list(FEATURE_NAMES), 'window_size': config['window_size'],
        'horizon': config['horizon'], 'window_config': config,
        'scaler': {'class': 'StandardScaler', 'fit_split': 'train_only',
                   'fit_sample_count': int(scaler.n_samples_seen_)},
        'label_map': payload['label_map'],
        'train_time_range': {'start': train_rows[0]['window_start'], 'end': train_rows[-1]['future_end']},
        'metrics_summary': report['baselines']['logistic_regression'],
        'sklearn_version': sklearn.__version__,
        'artifact_sha256': hashlib.sha256(model_path.read_bytes()).hexdigest(),
    }
    (MODELS_DIR / f'{MODEL_VERSION}_manifest.json').write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2, allow_nan=False) + '\n', encoding='utf-8')


def _matrix(rows):
    return np.asarray([[row['features'][name] for name in FEATURE_NAMES] for row in rows], dtype=float)


def _targets(rows):
    return np.asarray([int(row['label'] == 'WATCH') for row in rows])


def _scores(actual, predicted):
    tn, fp, fn, tp = confusion_matrix(actual, predicted, labels=[0, 1]).ravel()
    return {
        'accuracy': float(accuracy_score(actual, predicted)),
        'precision': float(precision_score(actual, predicted, zero_division=0)),
        'recall': float(recall_score(actual, predicted, zero_division=0)),
        'f1': float(f1_score(actual, predicted, zero_division=0)),
        'confusion_matrix': dict(zip(('TN', 'FP', 'FN', 'TP'), map(int, (tn, fp, fn, tp)))),
    }


def _analyze_errors(rows, targets, probabilities, original):
    # Match sklearn's two-class argmax: an exact tie selects NORMAL (class 0).
    predicted = (probabilities > 0.5).astype(int)
    wrong = [index for index in range(len(rows)) if predicted[index] != targets[index]]
    # Describe a few actual mistakes; if perfect, select the least confident case.
    selected = wrong[:3] if wrong else [int(np.argmin(np.abs(probabilities - 0.5)))]
    originals = {row['id']: row for row in original}
    results = []
    for index in selected:
        row = rows[index]
        kind = ('FN' if targets[index] else 'FP') if index in wrong else 'BOUNDARY'
        # Post-evaluation explanation only. Future values never enter X or fit.
        future = [originals[key] for key in row['future_sample_ids']]
        means = {key: sum(point[key] for point in future) / len(future)
                 for key in ('temperature', 'humidity', 'light')}
        triggered = []
        if means['temperature'] >= 32 or means['temperature'] <= 10:
            triggered.append('温度')
        if means['humidity'] <= 35 or means['humidity'] >= 85:
            triggered.append('湿度')
        if means['light'] >= 20000 or means['light'] <= 800:
            triggered.append('光照')
        feature = row['features']
        evidence = (f"输入当前光照为{feature['light_current']:.2f} lux、光照delta为{feature['light_delta']:.2f} lux；"
                    f"事后回查未来均值为温度{means['temperature']:.2f}°C、湿度{means['humidity']:.2f}%、光照{means['light']:.2f} lux")
        if kind == 'FN':
            explanation = f"假阴性：{evidence}，未来{'/'.join(triggered)}触发RULE_v1，但模型WATCH概率不超过0.5，漏掉了该提醒。"
        elif kind == 'FP':
            explanation = f"假阳性：{evidence}，未来三项均未触发RULE_v1，但模型WATCH概率高于0.5，产生误报。"
        else:
            explanation = f"测试集没有错分；选取WATCH概率最接近0.5的边界样本：{evidence}，此例预测正确但最接近固定决策阈值。"
        results.append({
            'sample_id': row['sample_id'], 'type': kind,
            'window_start': row['window_start'], 'window_end': row['window_end'],
            'future_start': row['future_start'], 'future_end': row['future_end'],
            'features': row['features'], 'true_label': row['label'],
            'predicted_label': 'WATCH' if predicted[index] else 'NORMAL',
            'predicted_probability_watch': float(probabilities[index]),
            'future_means_for_analysis_only': means, 'explanation': explanation,
        })
    return results


def train_and_evaluate() -> dict:
    settings = json.loads(dataset.CONFIG_PATH.read_text(encoding='utf-8')) if dataset.CONFIG_PATH.exists() else {}
    original = dataset.load_samples()
    windows, config = dataset._construct(original, settings.get('window_size', 6), settings.get('horizon', 2))
    train_rows = [row for row in windows if row['split'] == 'train']
    test_rows = [row for row in windows if row['split'] == 'test']
    distributions = {name: {label: Counter(row['label'] for row in rows)[label] for label in ('NORMAL', 'WATCH')}
                     for name, rows in (('train', train_rows), ('test', test_rows))}
    print('训练集/测试集类别分布：' + json.dumps(distributions, ensure_ascii=False), flush=True)
    if not train_rows or not test_rows:
        raise ValueError('训练集和测试集均必须非空；请检查样本和窗口配置。')
    x_train, y_train = _matrix(train_rows), _targets(train_rows)
    if len(np.unique(y_train)) != 2:
        raise ValueError('LogisticRegression 训练集必须同时包含 NORMAL 和 WATCH。')

    # ALL learning happens here and sees Train only. No Test arrays yet.
    majority = DummyClassifier(strategy='most_frequent', random_state=RANDOM_STATE)
    majority.fit(x_train, y_train)
    scaler = StandardScaler()
    x_train_scaled = scaler.fit_transform(x_train)
    model = LogisticRegression(max_iter=1000, random_state=RANDOM_STATE)
    model.fit(x_train_scaled, y_train)

    # Evaluation phase: Test is transformed with Train statistics, never fitted.
    x_test, y_test = _matrix(test_rows), _targets(test_rows)
    x_test_scaled = scaler.transform(x_test)
    baselines = {}
    for name, classifier, train_x, test_x in (
        ('majority', majority, x_train, x_test),
        ('logistic_regression', model, x_train_scaled, x_test_scaled),
    ):
        baselines[name] = {'train': _scores(y_train, classifier.predict(train_x)),
                           'test': _scores(y_test, classifier.predict(test_x))}
    watch_index = list(model.classes_).index(1)
    probabilities = model.predict_proba(x_test_scaled)[:, watch_index]
    majority_recall = baselines['majority']['test']['recall']
    ml_recall = baselines['logistic_regression']['test']['recall']
    conclusion = (f"测试集WATCH Recall：多数类基线={majority_recall:.4f}，逻辑回归={ml_recall:.4f}；"
                  f"{'改善' if ml_recall > majority_recall else '未改善'}（差值{ml_recall - majority_recall:+.4f}）。")
    report = {
        'model': {'name': 'LogisticRegression', 'max_iter': 1000, 'random_state': RANDOM_STATE,
                  'scaler': 'StandardScaler', 'threshold': 0.5, 'sklearn_version': sklearn.__version__},
        'features': list(FEATURE_NAMES), 'window_config': config,
        'generated_at': datetime.now(timezone.utc).isoformat(),
        'positive_class': 'WATCH', 'zero_division': 0,
        'train_count': len(train_rows), 'test_count': len(test_rows), 'class_distribution': distributions,
        'majority_class': 'WATCH' if int(majority.classes_[np.argmax(majority.class_prior_)]) else 'NORMAL',
        'baselines': baselines,
        'confusion_matrix': {name: {split: values['confusion_matrix'] for split, values in scores.items()}
                             for name, scores in baselines.items()},
        'recall_comparison': conclusion,
        'error_samples': _analyze_errors(test_rows, y_test, probabilities, original),
        'training_audit': {'fit_split': 'train_only', 'scaler_fit_sample_count': int(scaler.n_samples_seen_),
                           'scaler_mean': scaler.mean_.tolist(), 'model_saved': True},
    }
    _save_model(model, scaler, config, train_rows, report)
    METRICS_PATH.write_text(json.dumps(report, ensure_ascii=False, indent=2, allow_nan=False) + '\n', encoding='utf-8')
    print(json.dumps(report, ensure_ascii=False, indent=2, allow_nan=False))
    return report


if __name__ == '__main__':
    train_and_evaluate()
