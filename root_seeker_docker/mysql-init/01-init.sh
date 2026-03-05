#!/bin/bash
# MySQL 初始化：按顺序执行 SQL（SQL 文件已内置在 mysql-init/sql/）
# 首次启动时自动执行，表结构+若依系统+Git仓库+AI配置 全部就绪
set -e
SQL_DIR="/docker-entrypoint-initdb.d/sql"
for f in ry_20250416.sql quartz.sql git_source.sql git_source_repos_add_columns.sql git_source_demo.sql git_source_menu.sql app_config.sql app_config_menu.sql app_config_docker.sql git_source_menu_config.sql 001_analysis_status.sql 002_analysis_status_repo_id.sql 003_repo_index_status.sql 004_repo_index_status_single_field.sql; do
  [ -f "$SQL_DIR/$f" ] && mysql -u root -p"${MYSQL_ROOT_PASSWORD}" --default-character-set=utf8mb4 "${MYSQL_DATABASE}" < "$SQL_DIR/$f" || true
done
# Docker 环境：Admin 调用 RootSeeker 使用容器内服务名
mysql -u root -p"${MYSQL_ROOT_PASSWORD}" "${MYSQL_DATABASE}" -e "
  UPDATE sys_config SET config_value='http://root-seeker:8000' WHERE config_key='root.seeker.baseUrl';
  UPDATE sys_config SET config_value='http://root-seeker-admin:8080/gitsource/index/callback' WHERE config_key='root.seeker.adminCallbackUrl';
" 2>/dev/null || true
echo "MySQL init done"
