#!/bin/bash
# 重启 RootSeeker (8000) 和 Admin (8080)

set -e
cd "$(dirname "$0")/.."

echo "=== 停止旧进程 ==="
# 停止 8000 (RootSeeker)
for pid in $(lsof -ti :8000 2>/dev/null); do
  kill -9 $pid 2>/dev/null && echo "已停止 8000: $pid" || true
done
# 停止 8080 (Admin)
for pid in $(lsof -ti :8080 2>/dev/null); do
  kill -9 $pid 2>/dev/null && echo "已停止 8080: $pid" || true
done
sleep 2

echo "=== 启动 RootSeeker (8000) ==="
python3 -m uvicorn main:app --host 0.0.0.0 --port 8000 &
ROOTSEEKER_PID=$!
sleep 5
if kill -0 $ROOTSEEKER_PID 2>/dev/null; then
  echo "RootSeeker 已启动 PID=$ROOTSEEKER_PID"
else
  echo "RootSeeker 启动失败"
  exit 1
fi

echo "=== 启动 Admin (8080) ==="
# 加载 .env，确保 MySQL 配置正确传递（否则会使用 application-druid.yml 默认 localhost:3306）
[[ -f .env ]] && set -a && source .env && set +a
export MYSQL_HOST="${MYSQL_HOST:-localhost}"
export MYSQL_PORT="${MYSQL_PORT:-3306}"
export MYSQL_USERNAME="${MYSQL_USERNAME:-root}"
export MYSQL_PASSWORD="${MYSQL_PASSWORD:-password}"
export MYSQL_DATABASE="${MYSQL_DATABASE:-root_seeker}"
echo "MySQL: $MYSQL_HOST:$MYSQL_PORT/$MYSQL_DATABASE"
cd ruoyi-rootseeker-admin
DRUID_URL="jdbc:mysql://${MYSQL_HOST}:${MYSQL_PORT}/${MYSQL_DATABASE}?useUnicode=true&characterEncoding=UTF-8&connectionCollation=utf8mb4_unicode_ci&zeroDateTimeBehavior=convertToNull&useSSL=false&allowPublicKeyRetrieval=true&serverTimezone=GMT%2B8"
env MYSQL_HOST="$MYSQL_HOST" MYSQL_PORT="$MYSQL_PORT" MYSQL_USERNAME="$MYSQL_USERNAME" MYSQL_PASSWORD="$MYSQL_PASSWORD" MYSQL_DATABASE="$MYSQL_DATABASE" \
  SPRING_DATASOURCE_DRUID_MASTER_URL="$DRUID_URL" mvn spring-boot:run -pl ruoyi-admin &
ADMIN_PID=$!
cd - >/dev/null
echo "Admin 启动中 (PID=$ADMIN_PID)，约需 40-60 秒..."
echo "RootSeeker: http://localhost:8000"
echo "Admin: http://localhost:8080"
