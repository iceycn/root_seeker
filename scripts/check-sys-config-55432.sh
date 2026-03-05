#!/bin/bash
# 查询 sys_config 中是否含 55432 或 MySQL 相关配置
# 用法: bash scripts/check-sys-config-55432.sh

set -e
cd "$(dirname "$0")/.."
[[ -f .env ]] && set -a && source .env && set +a

MYSQL_HOST="${MYSQL_HOST:-localhost}"
MYSQL_PORT="${MYSQL_PORT:-3306}"
MYSQL_USERNAME="${MYSQL_USERNAME:-root}"
MYSQL_PASSWORD="${MYSQL_PASSWORD:?请设置 MYSQL_PASSWORD}"
MYSQL_DATABASE="${MYSQL_DATABASE:-root_seeker}"

echo "=== 查询 sys_config 中 55432 / MySQL / datasource 相关配置 ==="
echo "连接 $MYSQL_HOST:$MYSQL_PORT/$MYSQL_DATABASE"
echo ""

mysql -h "$MYSQL_HOST" -P "$MYSQL_PORT" -u "$MYSQL_USERNAME" -p"$MYSQL_PASSWORD" "$MYSQL_DATABASE" -e "
SELECT config_id, config_key, LEFT(config_value, 120) AS config_value_preview 
FROM sys_config 
WHERE config_value LIKE '%55432%' 
   OR config_value LIKE '%47.100.101.21%' 
   OR config_key LIKE '%mysql%' 
   OR config_key LIKE '%datasource%'
   OR config_value LIKE '%53266%';
" 2>/dev/null || {
  echo "连接失败，请检查 .env 中的 MYSQL_* 配置"
  exit 1
}

echo ""
echo "若上表有含 55432 的记录，可执行修复: mysql ... < scripts/fix-mysql-port-55432-to-53266.sql"
