-- MySQL 初始化入口：用 source 串联执行，确保顺序一致
-- 注意：这些命令由 mysql 客户端执行（docker-entrypoint-initdb.d 机制）

SET SESSION sql_mode='';
SET NAMES utf8mb4;

source /docker-entrypoint-initdb.d/src/ry_20250416.sql;
source /docker-entrypoint-initdb.d/src/quartz.sql;
source /docker-entrypoint-initdb.d/src/git_source.sql;
source /docker-entrypoint-initdb.d/src/git_source_repos_add_columns.sql;
source /docker-entrypoint-initdb.d/src/git_source_demo.sql;
source /docker-entrypoint-initdb.d/src/git_source_menu.sql;
source /docker-entrypoint-initdb.d/src/app_config.sql;
source /docker-entrypoint-initdb.d/src/app_config_menu.sql;
source /docker-entrypoint-initdb.d/src/app_config_docker.sql;
source /docker-entrypoint-initdb.d/src/git_source_menu_config.sql;
source /docker-entrypoint-initdb.d/src/001_analysis_status.sql;
source /docker-entrypoint-initdb.d/src/002_analysis_status_repo_id.sql;
source /docker-entrypoint-initdb.d/src/003_repo_index_status.sql;
source /docker-entrypoint-initdb.d/src/004_repo_index_status_single_field.sql;

UPDATE sys_config SET config_value='http://root-seeker:8000' WHERE config_key='root.seeker.baseUrl';
UPDATE sys_config SET config_value='http://root-seeker-admin:8080/gitsource/index/callback' WHERE config_key='root.seeker.adminCallbackUrl';
