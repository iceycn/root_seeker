#!/usr/bin/env bash
# 一键启动：Qdrant、Zoekt、RootSeeker、RootSeeker Admin（后台运行）
# 用法: bash scripts/start-all-one-click.sh
# 停止: bash scripts/stop-all-one-click.sh

set -e
cd "$(dirname "$0")/.."
PROJECT_ROOT="$(pwd)"

LOG_DIR="${PROJECT_ROOT}/logs"
PID_FILE="${LOG_DIR}/start-all.pid"
mkdir -p "$LOG_DIR"
: > "$PID_FILE"  # 清空 PID 文件

# 记录 PID 用于停止
PIDS=()

cleanup() {
  echo ""
  echo "已启动的服务:"
  echo "  - RootSeeker:      http://localhost:8000"
  echo "  - RootSeeker Admin: http://localhost:8080"
  echo "  - Qdrant:          http://localhost:6333"
  echo "  - Zoekt:           http://localhost:6070"
  echo ""
  echo " 日志: $LOG_DIR/"
  echo " 停止: bash scripts/stop-all-one-click.sh"
  echo ""
}

# 启动 Qdrant
if [[ -x "${PROJECT_ROOT}/tools/qdrant" ]]; then
  if lsof -ti :6333 >/dev/null 2>&1; then
    echo "[Qdrant] 端口 6333 已占用，跳过"
  else
    echo "[Qdrant] 启动中..."
    nohup "${PROJECT_ROOT}/tools/qdrant" --config-path "${PROJECT_ROOT}/config/qdrant_config.yaml" \
      >> "${LOG_DIR}/qdrant.log" 2>&1 &
    PIDS+=($!)
    echo $! >> "$PID_FILE"
    sleep 1
    echo "[Qdrant] 已启动 (PID $!)"
  fi
else
  echo "[Qdrant] 未找到 tools/qdrant，跳过（可执行 bash scripts/install-without-docker.sh 安装）"
fi

# 启动 Zoekt
INDEX_DIR="${PROJECT_ROOT}/data/zoekt/index"
ZOOKT_BIN=""
if command -v zoekt-webserver &>/dev/null; then
  ZOOKT_BIN="zoekt-webserver"
elif [[ -x "$(go env GOPATH 2>/dev/null)/bin/zoekt-webserver" ]]; then
  ZOOKT_BIN="$(go env GOPATH)/bin/zoekt-webserver"
fi
if [[ -n "$ZOOKT_BIN" && -d "$INDEX_DIR" ]]; then
  if lsof -ti :6070 >/dev/null 2>&1; then
    echo "[Zoekt] 端口 6070 已占用，跳过"
  else
    echo "[Zoekt] 启动中..."
    nohup "$ZOOKT_BIN" -index "$INDEX_DIR" -listen :6070 -rpc \
      >> "${LOG_DIR}/zoekt.log" 2>&1 &
    PIDS+=($!)
    echo $! >> "$PID_FILE"
    sleep 1
    echo "[Zoekt] 已启动 (PID $!)"
  fi
else
  echo "[Zoekt] 未安装或索引不存在，跳过（需先 bash scripts/index-zoekt-all.sh）"
fi

# 启动 RootSeeker (Python)
if lsof -ti :8000 >/dev/null 2>&1; then
  echo "[RootSeeker] 端口 8000 已占用，跳过"
else
  echo "[RootSeeker] 启动中..."
  nohup python3 -m uvicorn main:app --host 0.0.0.0 --port 8000 \
    >> "${LOG_DIR}/root-seeker.log" 2>&1 &
  PIDS+=($!)
  echo $! >> "$PID_FILE"
  sleep 2
  echo "[RootSeeker] 已启动 (PID $!)"
fi

# 启动 RootSeeker Admin (Java)
if [[ -d "${PROJECT_ROOT}/ruoyi-rootseeker-admin" ]]; then
  if lsof -ti :8080 >/dev/null 2>&1; then
    echo "[RootSeeker Admin] 端口 8080 已占用，跳过"
  else
    echo "[RootSeeker Admin] 启动中（首次需下载依赖，较慢）..."
    cd "${PROJECT_ROOT}/ruoyi-rootseeker-admin"
    nohup mvn spring-boot:run -pl ruoyi-admin -q \
      >> "${LOG_DIR}/root-seeker-admin.log" 2>&1 &
    echo $! >> "$PID_FILE"
    cd "$PROJECT_ROOT"
    sleep 2
    echo "[RootSeeker Admin] 已启动"
  fi
else
  echo "[RootSeeker Admin] 未找到 ruoyi-rootseeker-admin 目录，跳过"
fi

cleanup
