#!/usr/bin/env bash
# 重启：先停止 start-all-one-click 启动的服务，再一键启动
# 用法: bash scripts/restart-all-one-click.sh

set -e
cd "$(dirname "$0")/.."

echo "=== 停止服务 ==="
bash scripts/stop-all-one-click.sh

sleep 3

echo ""
echo "=== 启动服务 ==="
bash scripts/start-all-one-click.sh

echo ""
echo "日志: logs/root-seeker.log, logs/root-seeker-admin.log"
echo "Admin 约需 40-60 秒启动，若 MySQL 连接失败请检查 .env 中 MYSQL_HOST/MYSQL_PORT"
