#!/bin/bash
# 查询指定仓库的 repo_index_status 与 git_source_repos
# 用法: bash scripts/check-repo-status.sh [service_name]
# 示例: bash scripts/check-repo-status.sh api-gateway

cd "$(dirname "$0")/.."
[[ -f .env ]] && set -a && source .env && set +a

HOST="${MYSQL_HOST:-localhost}"
PORT="${MYSQL_PORT:-3306}"
USER="${MYSQL_USERNAME:-root}"
PASS="${MYSQL_PASSWORD:-password}"
DB="${MYSQL_DATABASE:-root_seeker}"
PAT="${1:-%gateway%}"

echo "=== git_source_repos (full_name like '%$PAT%') ==="
mysql -h "$HOST" -P "$PORT" -u "$USER" -p"$PASS" "$DB" -e "
SELECT id, full_name, full_path, enabled, 
       REPLACE(COALESCE(full_name, full_path, id), '/', '-') as service_name_calc
FROM git_source_repos 
WHERE full_name LIKE '%$PAT%' OR full_path LIKE '%$PAT%' OR id LIKE '%$PAT%';
" 2>/dev/null || echo "MySQL 连接失败，请检查 .env 或环境变量"

echo ""
echo "=== repo_index_status (service_name like '%$PAT%') ==="
mysql -h "$HOST" -P "$PORT" -u "$USER" -p"$PASS" "$DB" -e "
SELECT service_name, qdrant_indexed, qdrant_indexing, qdrant_count, zoekt_indexed, zoekt_indexing, updated_at
FROM repo_index_status 
WHERE service_name LIKE '%$PAT%';
" 2>/dev/null || echo "MySQL 连接失败"
