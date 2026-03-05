-- 修复 Admin 回调地址：若误配置为 RootSeeker 端口 8000，改为 Admin 端口 8080
-- 执行：mysql -u 用户名 -p 数据库名 < scripts/fix-admin-callback-url-8000-to-8080.sql

UPDATE sys_config
SET config_value = 'http://localhost:8080/gitsource/index/callback'
WHERE config_key = 'root.seeker.adminCallbackUrl'
  AND (config_value LIKE '%localhost:8000%' OR config_value LIKE '%127.0.0.1:8000%');
