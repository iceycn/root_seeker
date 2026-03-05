#!/usr/bin/env bash
# 按顺序执行 SQL 到 MySQL（使用 .env 或环境变量）
# 用法: bash scripts/exec-sql.sh
# 需先创建 .env：cp .env.example .env && 编辑填入 MYSQL_PASSWORD

set -e
cd "$(dirname "$0")/.."

if [ -f .env ]; then
  set -a
  source .env
  set +a
  echo "已加载 .env"
fi

MYSQL_HOST="${MYSQL_HOST:?请设置 MYSQL_HOST 或创建 .env}"
MYSQL_PORT="${MYSQL_PORT:-3306}"
MYSQL_USERNAME="${MYSQL_USERNAME:-root}"
MYSQL_PASSWORD="${MYSQL_PASSWORD:?请设置 MYSQL_PASSWORD 或创建 .env}"
MYSQL_DATABASE="${MYSQL_DATABASE:-root_seeker}"

SQL_DIR="root_seeker_docker/mysql-init/sql"
FILES="ry_20250416.sql quartz.sql git_source.sql git_source_repos_add_columns.sql git_source_demo.sql git_source_menu.sql app_config.sql app_config_menu.sql app_config_docker.sql git_source_menu_config.sql"

echo "连接 $MYSQL_HOST:$MYSQL_PORT/$MYSQL_DATABASE ..."
mysql -h "$MYSQL_HOST" -P "$MYSQL_PORT" -u "$MYSQL_USERNAME" -p"$MYSQL_PASSWORD" -e "SELECT 1" "$MYSQL_DATABASE" 2>/dev/null || {
  echo "错误: 无法连接 MySQL，请检查网络、防火墙或 VPN"
  exit 1
}
for f in $FILES; do
  if [ -f "$SQL_DIR/$f" ]; then
    echo "执行 $f ..."
    mysql -h "$MYSQL_HOST" -P "$MYSQL_PORT" -u "$MYSQL_USERNAME" -p"$MYSQL_PASSWORD" \
      --default-character-set=utf8mb4 "$MYSQL_DATABASE" < "$SQL_DIR/$f" || { echo "警告: $f 执行失败"; }
  else
    echo "跳过 $f (文件不存在)"
  fi
done

# 非 Docker 环境：RootSeeker 地址改为 localhost
mysql -h "$MYSQL_HOST" -P "$MYSQL_PORT" -u "$MYSQL_USERNAME" -p"$MYSQL_PASSWORD" "$MYSQL_DATABASE" -e "
  UPDATE sys_config SET config_value='http://localhost:8000' WHERE config_key='root.seeker.baseUrl';
" 2>/dev/null || true

echo "SQL 执行完成"
