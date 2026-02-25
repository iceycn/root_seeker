#!/usr/bin/env bash
# 重启前先停掉占用端口的 RootSeeker/uvicorn 进程
# 用法: bash scripts/stop-server.sh [端口号]
# 默认端口 8000，可通过环境变量 PORT 覆盖，例如: PORT=8001 bash scripts/stop-server.sh

set -e
PORT="${PORT:-${1:-8000}}"
if ! [[ "$PORT" =~ ^[0-9]+$ ]]; then
  echo "用法: bash scripts/stop-server.sh [端口号]" >&2
  echo "或: PORT=8001 bash scripts/stop-server.sh" >&2
  exit 1
fi

# macOS: lsof -i :PORT 取占用该端口的 PID
if command -v lsof >/dev/null 2>&1; then
  PIDS=$(lsof -ti ":$PORT" 2>/dev/null || true)
  if [ -z "$PIDS" ]; then
    echo "端口 $PORT 无占用进程"
    exit 0
  fi
  echo "正在终止占用端口 $PORT 的进程: $PIDS"
  echo "$PIDS" | xargs kill -9 2>/dev/null || true
  echo "已终止"
  exit 0
fi

# Linux 等: 用 ss 或 netstat
if command -v ss >/dev/null 2>&1; then
  PID=$(ss -tlnp 2>/dev/null | awk -v port=":$PORT" '$4 ~ port { gsub(/.*pid=/, "", $6); print $6; exit }')
elif command -v netstat >/dev/null 2>&1; then
  PID=$(netstat -tlnp 2>/dev/null | awk -v port=":$PORT " '$4 ~ port { print $7; exit }' | cut -d/ -f1)
else
  echo "未找到 lsof/ss/netstat，请手动结束占用端口 $PORT 的进程" >&2
  exit 1
fi
if [ -z "$PID" ]; then
  echo "端口 $PORT 无占用进程"
  exit 0
fi
echo "正在终止占用端口 $PORT 的进程: $PID"
kill -9 "$PID" 2>/dev/null || true
echo "已终止"
