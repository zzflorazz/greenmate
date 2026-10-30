#!/usr/bin/env bash
set -euo pipefail
cd -- "$(dirname -- "${BASH_SOURCE[0]}")"
if [[ ! -f .venv/bin/activate ]]; then
  echo '启动失败：找不到 .venv。请先创建虚拟环境并安装 requirements.txt。' >&2
  exit 1
fi
if [[ ! -f .env ]]; then
  echo '启动失败：缺少 .env。请执行 cp .env.example .env，填写配置后再运行 ./run.sh。' >&2
  exit 1
fi
source .venv/bin/activate
python settings.py
port="${1:-8100}"
printf '%s\n' "GreenMate 即将启动：http://127.0.0.1:${port}（按 Ctrl+C 停止）"
exec python -m uvicorn main:app --host 127.0.0.1 --port "$port"
