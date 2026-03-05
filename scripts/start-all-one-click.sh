#!/usr/bin/env bash
# 一键启动：Qdrant、Zoekt、RootSeeker、RootSeeker Admin（后台运行）
# 用法: bash scripts/start-all-one-click.sh
# 停止: bash scripts/stop-all-one-click.sh

set -e
cd "$(dirname "$0")/.."
PROJECT_ROOT="$(pwd)"

# 加载 .env，确保 MySQL 使用 .env 配置（否则会回退到 localhost:3306）
[[ -f "${PROJECT_ROOT}/.env" ]] && set -a && source "${PROJECT_ROOT}/.env" && set +a

LOG_DIR="${PROJECT_ROOT}/logs"
PID_FILE="${LOG_DIR}/start-all.pid"
mkdir -p "$LOG_DIR"
: > "$PID_FILE"  # 清空 PID 文件

# 记录 PID 用于停止
PIDS=()
ADMIN_PORT="${ROOTSEEKER_ADMIN_PORT:-${ADMIN_PORT:-8080}}"
ADMIN_ALLOW_FALLBACK="${ROOTSEEKER_ADMIN_ALLOW_FALLBACK:-${ADMIN_ALLOW_FALLBACK:-0}}"
ADMIN_FALLBACK_PORT="${ROOTSEEKER_ADMIN_FALLBACK_PORT:-${ADMIN_FALLBACK_PORT:-18080}}"
ADMIN_STARTED=0
ADMIN_RUN_MODE="${ROOTSEEKER_ADMIN_RUN_MODE:-${ADMIN_RUN_MODE:-auto}}"
ADMIN_PROFILE="${ROOTSEEKER_ADMIN_PROFILE:-${SPRING_PROFILES_ACTIVE:-${ENV:-local}}}"

get_pid_cmd() {
  ps -p "$1" -o command= 2>/dev/null || true
}

is_managed_pid() {
  local cmd
  cmd="$(get_pid_cmd "$1")"
  [[ -z "$cmd" ]] && return 1
  [[ "$cmd" == *"$PROJECT_ROOT"* ]] && return 0
  [[ "$cmd" == *"ruoyi-admin.jar"* ]] && return 0
  [[ "$cmd" == *"uvicorn main:app"* ]] && return 0
  return 1
}

is_port_used() {
  lsof -nP -tiTCP:"$1" -sTCP:LISTEN >/dev/null 2>&1
}

get_port_pids() {
  lsof -nP -tiTCP:"$1" -sTCP:LISTEN 2>/dev/null || true
}

cleanup() {
  echo ""
  echo "已启动的服务:"
  echo "  - RootSeeker:      http://localhost:8000"
  if [[ "$ADMIN_STARTED" -eq 1 ]]; then
    echo "  - RootSeeker Admin: http://localhost:${ADMIN_PORT}"
  else
    echo "  - RootSeeker Admin: 未启动（期望端口: ${ADMIN_PORT}）"
  fi
  echo "  - Qdrant:          http://localhost:6333"
  echo "  - Zoekt:           http://localhost:6070"
  echo ""
  echo " 日志: $LOG_DIR/"
  echo " 停止: bash scripts/stop-all-one-click.sh"
  echo ""
}

# 启动 Qdrant
if [[ -x "${PROJECT_ROOT}/tools/qdrant" ]]; then
  if is_port_used 6333; then
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
  if is_port_used 6070; then
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
if is_port_used 8000; then
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
  if is_port_used "$ADMIN_PORT"; then
    PIDS_ON_PORT="$(get_port_pids "$ADMIN_PORT")"
    HAS_MANAGED=0
    for pid in $PIDS_ON_PORT; do
      if is_managed_pid "$pid"; then
        HAS_MANAGED=1
        break
      fi
    done
    if [[ "$HAS_MANAGED" -eq 1 ]]; then
      echo "[RootSeeker Admin] 端口 $ADMIN_PORT 已被项目进程占用，跳过"
    else
      if [[ "$ADMIN_ALLOW_FALLBACK" == "1" ]]; then
        NEW_PORT=""
        for p in $(seq "$ADMIN_FALLBACK_PORT" "$((ADMIN_FALLBACK_PORT + 9))"); do
          if ! is_port_used "$p"; then
            NEW_PORT="$p"
            break
          fi
        done
        if [[ -z "$NEW_PORT" ]]; then
          echo "[RootSeeker Admin] 端口 $ADMIN_PORT 已被非项目进程占用且找不到可用备用端口，跳过"
        else
          echo "[RootSeeker Admin] 端口 $ADMIN_PORT 已被非项目进程占用，改用端口 $NEW_PORT 启动"
          ADMIN_PORT="$NEW_PORT"
        fi
      else
        echo "[RootSeeker Admin] 端口 $ADMIN_PORT 已被非项目进程占用，固定端口模式不切换，跳过"
      fi
    fi
  fi
  if [[ "$ADMIN_STARTED" -eq 0 ]]; then
    if is_port_used "$ADMIN_PORT"; then
      true
    else
    export MYSQL_HOST="${MYSQL_HOST:-localhost}"
    export MYSQL_PORT="${MYSQL_PORT:-3306}"
    export MYSQL_USERNAME="${MYSQL_USERNAME:-root}"
    export MYSQL_PASSWORD="${MYSQL_PASSWORD:-}"
    export MYSQL_DATABASE="${MYSQL_DATABASE:-root_seeker}"
    echo "[RootSeeker Admin] MySQL: $MYSQL_HOST:$MYSQL_PORT/$MYSQL_DATABASE (profile=$ADMIN_PROFILE)"
    if [[ ! -f "${PROJECT_ROOT}/.env" ]]; then
      echo "[RootSeeker Admin] 提示: 未找到 .env，使用默认 localhost。可 cp .env.example .env 并编辑"
    fi
    ADMIN_JAR="${PROJECT_ROOT}/ruoyi-rootseeker-admin/ruoyi-admin/target/ruoyi-admin.jar"
    if [[ "$ADMIN_RUN_MODE" != "mvn" && -f "$ADMIN_JAR" ]]; then
      echo "[RootSeeker Admin] 启动中（java -jar，profile=$ADMIN_PROFILE，port=$ADMIN_PORT）..."
      cd "${PROJECT_ROOT}/ruoyi-rootseeker-admin"
      nohup env MYSQL_HOST="$MYSQL_HOST" MYSQL_PORT="$MYSQL_PORT" MYSQL_USERNAME="$MYSQL_USERNAME" MYSQL_PASSWORD="$MYSQL_PASSWORD" MYSQL_DATABASE="$MYSQL_DATABASE" SPRING_PROFILES_ACTIVE="$ADMIN_PROFILE" \
        SERVER_PORT="$ADMIN_PORT" \
        java -jar "$ADMIN_JAR" >> "${LOG_DIR}/root-seeker-admin.log" 2>&1 &
    else
      echo "[RootSeeker Admin] 启动中（mvn spring-boot:run，profile=$ADMIN_PROFILE，port=$ADMIN_PORT）..."
      cd "${PROJECT_ROOT}/ruoyi-rootseeker-admin"
      nohup env MYSQL_HOST="$MYSQL_HOST" MYSQL_PORT="$MYSQL_PORT" MYSQL_USERNAME="$MYSQL_USERNAME" MYSQL_PASSWORD="$MYSQL_PASSWORD" MYSQL_DATABASE="$MYSQL_DATABASE" SPRING_PROFILES_ACTIVE="$ADMIN_PROFILE" \
        SERVER_PORT="$ADMIN_PORT" \
        mvn spring-boot:run -pl ruoyi-admin -q \
        >> "${LOG_DIR}/root-seeker-admin.log" 2>&1 &
    fi
    echo $! >> "$PID_FILE"
    cd "$PROJECT_ROOT"
    sleep 2
    echo "[RootSeeker Admin] 已启动"
    ADMIN_STARTED=1
    fi
  fi
else
  echo "[RootSeeker Admin] 未找到 ruoyi-rootseeker-admin 目录，跳过"
fi

cleanup
