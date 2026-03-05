#!/usr/bin/env bash
# 停止一键启动的所有服务
# 用法: bash scripts/stop-all-one-click.sh

set -e
cd "$(dirname "$0")/.."
PROJECT_ROOT="$(pwd)"
LOG_DIR="${PROJECT_ROOT}/logs"
PID_FILE="${LOG_DIR}/start-all.pid"

echo "=== 停止服务 ==="

get_pid_cmd() {
  ps -p "$1" -o command= 2>/dev/null || true
}

is_managed_pid() {
  local cmd
  cmd="$(get_pid_cmd "$1")"
  [[ -z "$cmd" ]] && return 1
  [[ "$cmd" == *"$PROJECT_ROOT"* ]] && return 0
  [[ "$cmd" == *"uvicorn main:app"* ]] && return 0
  return 1
}

# 按 PID 文件停止
if [[ -f "$PID_FILE" ]]; then
  while read -r pid; do
    [[ -z "$pid" || ! "$pid" =~ ^[0-9]+$ ]] && continue
    if kill -0 "$pid" 2>/dev/null; then
      echo "  终止 PID $pid"
      kill -9 "$pid" 2>/dev/null || true
    fi
  done < "$PID_FILE"
  rm -f "$PID_FILE"
  echo "  已按 PID 文件停止"
fi

# 按端口停止（兜底，防止 PID 文件丢失）
for port in 8000 8080 18080 18081 18082 18083 18084 18085 18086 18087 18088 18089 6333 6070; do
  if command -v lsof >/dev/null 2>&1; then
    PIDS=$(lsof -nP -tiTCP:"$port" -sTCP:LISTEN 2>/dev/null || true)
    if [[ -n "$PIDS" ]]; then
      for pid in $PIDS; do
        if is_managed_pid "$pid"; then
          echo "  终止占用端口 $port 的项目进程: $pid"
          kill -9 "$pid" 2>/dev/null || true
        else
          cmd="$(get_pid_cmd "$pid")"
          echo "  跳过占用端口 $port 的非项目进程: $pid ${cmd}"
        fi
      done
    fi
  fi
done

echo "  完成"
