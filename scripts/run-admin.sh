#!/usr/bin/env bash
# 使用 .env 环境变量启动 Admin 管理端
# 用法: bash scripts/run-admin.sh

set -e
cd "$(dirname "$0")/.."

if [ -f .env ]; then
  set -a
  source .env
  set +a
  echo "已加载 .env"
fi

export MYSQL_HOST="${MYSQL_HOST:-localhost}"
export MYSQL_PORT="${MYSQL_PORT:-3306}"
export MYSQL_USERNAME="${MYSQL_USERNAME:-root}"
export MYSQL_PASSWORD="${MYSQL_PASSWORD:-password}"
export MYSQL_DATABASE="${MYSQL_DATABASE:-root_seeker}"

# 显式设置数据源 URL，覆盖任何外部环境变量
export SPRING_DATASOURCE_DRUID_MASTER_URL="jdbc:mysql://${MYSQL_HOST}:${MYSQL_PORT}/${MYSQL_DATABASE}?useUnicode=true&characterEncoding=UTF-8&connectionCollation=utf8mb4_unicode_ci&zeroDateTimeBehavior=convertToNull&useSSL=false&allowPublicKeyRetrieval=true&serverTimezone=GMT%2B8"

cd ruoyi-rootseeker-admin
mvn spring-boot:run -pl ruoyi-admin
