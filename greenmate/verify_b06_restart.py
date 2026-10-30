"""Start/stop two fresh FastAPI processes; fitted artifacts must survive both."""
import hashlib
import json
import os
import socket
import subprocess
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent


def verify():
    files = [ROOT / 'models/attention_v1.joblib', ROOT / 'models/attention_v1_manifest.json']
    before = {path.name: hashlib.sha256(path.read_bytes()).hexdigest() for path in files}
    results = []
    logs = ROOT / 'verification/b06_restart.log'
    logs.parent.mkdir(exist_ok=True)
    with logs.open('w', encoding='utf-8') as log:
        for attempt in (1, 2):
            with socket.socket() as sock:
                sock.bind(('127.0.0.1', 0))
                port = sock.getsockname()[1]
            # The normal FastAPI lifespan runs; any fitting would fail this check.
            code = '''import sys
from unittest.mock import patch
import uvicorn
with patch('sklearn.linear_model.LogisticRegression.fit', side_effect=RuntimeError('verification forbids retraining')), patch('sklearn.preprocessing.StandardScaler.fit', side_effect=RuntimeError('verification forbids scaler fitting')):
    uvicorn.run('main:app', host='127.0.0.1', port=int(sys.argv[1]), log_level='info')
'''
            process = subprocess.Popen([sys.executable, '-c', code, str(port)], cwd=ROOT,
                                       env={**os.environ, 'HF_HUB_OFFLINE': '1'}, stdout=log, stderr=log)
            try:
                deadline = time.monotonic() + 45
                while True:
                    if process.poll() is not None:
                        raise RuntimeError(f'Server exited before startup; see {logs}')
                    try:
                        with urllib.request.urlopen(f'http://127.0.0.1:{port}/api/ml/predict', timeout=2) as response:
                            prediction = json.load(response)
                        break
                    except (urllib.error.URLError, TimeoutError):
                        if time.monotonic() >= deadline:
                            raise RuntimeError('Server startup timeout')
                        time.sleep(0.2)
                assert prediction['status'] == 'ok', prediction
                assert prediction['model_version'] == 'attention_v1'
                results.append({'attempt': attempt, 'pid': process.pid, 'prediction': prediction})
            finally:
                process.terminate()
                try:
                    process.wait(timeout=10)
                except subprocess.TimeoutExpired:
                    process.kill()
                    process.wait()
    after = {path.name: hashlib.sha256(path.read_bytes()).hexdigest() for path in files}
    assert before == after
    assert results[0]['pid'] != results[1]['pid']
    report = {'mode': 'two_fresh_servers_normal_lifespan_training_disabled',
              'artifact_hashes_unchanged': before == after, 'artifact_sha256': after, 'results': results}
    (ROOT / 'verification/b06_restart.json').write_text(json.dumps(report, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    print(json.dumps(report, ensure_ascii=False, indent=2))


if __name__ == '__main__':
    verify()
