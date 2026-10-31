#!/usr/bin/env bash
set -euo pipefail

cd "$(dirname "$0")"

echo "启动文献整理助手..."
echo "首次运行会安装依赖（PowerContext 1.2.0）"

if [ ! -d ".venv" ]; then
  python -m venv .venv
fi

if [ -x ".venv/bin/python" ]; then
  PY=.venv/bin/python
else
  PY=.venv/Scripts/python.exe
fi

"$PY" -m pip install -r requirements.txt
echo "服务地址: http://127.0.0.1:8000"
exec "$PY" backend/main.py
