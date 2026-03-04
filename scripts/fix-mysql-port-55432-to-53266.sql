-- 若 sys_config 中存在含 55432 的 MySQL 相关配置，改为 53266
-- 执行: mysql -h HOST -P PORT -u USER -p root_seeker < scripts/fix-mysql-port-55432-to-53266.sql

UPDATE sys_config 
SET config_value = REPLACE(config_value, '55432', '53266') 
WHERE config_value LIKE '%55432%';

SELECT config_id, config_key, config_value 
FROM sys_config 
WHERE config_key LIKE '%mysql%' OR config_key LIKE '%datasource%' OR config_value LIKE '%55432%' OR config_value LIKE '%53266%';
