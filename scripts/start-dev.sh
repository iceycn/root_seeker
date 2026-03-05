#!/usr/bin/env bash
# 开发模式启动：代码变更时自动重启
# 用法: bash scripts/start-dev.sh

set -e
cd "$(dirname "$0")/.."

PORT="${PORT:-8000}"
echo "停止占用端口 $PORT 的旧进程..."
bash scripts/stop-server.sh "$PORT" 2>/dev/null || true

echo ""
echo "启动 RootSeeker（--reload 监听代码变更自动重启）..."
export TOKENIZERS_PARALLELISM=false
python3 -m uvicorn main:app --host 0.0.0.0 --port "$PORT" --reload
