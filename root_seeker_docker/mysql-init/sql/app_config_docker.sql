-- Docker 编排模式：完整 Demo 配置，开箱即用
-- config_source=database，所有配置从 app_config 读取，Admin「AI应用配置」可管理
-- 使用 ON DUPLICATE KEY UPDATE 确保初始化时始终写入

-- 1. 配置来源：数据库模式
INSERT INTO app_config (config_category, config_key, config_value, description, sort_order, created_at, updated_at)
VALUES ('system', 'config_source', 'database', '配置来源：database=从本表读取', 0, sysdate(), sysdate())
ON DUPLICATE KEY UPDATE config_value='database', updated_at=sysdate();

-- 2. Qdrant（容器内服务名）
INSERT INTO app_config (config_category, config_key, config_value, description, sort_order, created_at, updated_at)
VALUES ('qdrant', 'default', '{"url":"http://qdrant:6333","api_key":null,"collection":"code_chunks"}', 'Qdrant 向量库', 10, sysdate(), sysdate())
ON DUPLICATE KEY UPDATE config_value=VALUES(config_value), updated_at=sysdate();

-- 3. Zoekt（容器内服务名）
INSERT INTO app_config (config_category, config_key, config_value, description, sort_order, created_at, updated_at)
VALUES ('zoekt', 'default', '{"api_base_url":"http://zoekt:6070"}', 'Zoekt 代码搜索', 20, sysdate(), sysdate())
ON DUPLICATE KEY UPDATE config_value=VALUES(config_value), updated_at=sysdate();

-- 4. LLM（Demo：DeepSeek，需在 Admin 中填写 api_key）
INSERT INTO app_config (config_category, config_key, config_value, description, sort_order, created_at, updated_at)
VALUES ('llm', 'default', '{"kind":"deepseek","base_url":"https://api.deepseek.com","api_key":"","model":"deepseek-chat","timeout_seconds":90}', 'LLM 配置，请在 Admin 中填写 api_key 后使用', 30, sysdate(), sysdate())
ON DUPLICATE KEY UPDATE config_value=VALUES(config_value), updated_at=sysdate();

-- 5. Embedding（本地 fastembed，无需 API）
INSERT INTO app_config (config_category, config_key, config_value, description, sort_order, created_at, updated_at)
VALUES ('embedding', 'default', '{"kind":"fastembed","model_name":"BAAI/bge-small-en-v1.5"}', 'Embedding 本地模型', 40, sysdate(), sysdate())
ON DUPLICATE KEY UPDATE config_value=VALUES(config_value), updated_at=sysdate();

-- 6. 阿里云 SLS（Demo 占位，需填写真实凭证）
INSERT INTO app_config (config_category, config_key, config_value, description, sort_order, created_at, updated_at)
VALUES ('aliyun_sls', 'default', '{"endpoint":"https://cn-hangzhou.log.aliyuncs.com","access_key_id":"","access_key_secret":"","project":"your-project","logstore":"your-logstore","topic":null}', '阿里云日志服务，需填写 access_key 等', 50, sysdate(), sysdate())
ON DUPLICATE KEY UPDATE config_value=VALUES(config_value), updated_at=sysdate();

-- 7. 企微（Demo 占位）
INSERT INTO app_config (config_category, config_key, config_value, description, sort_order, created_at, updated_at)
VALUES ('wecom', 'default', '{"webhook_url":"","secret":"","security_mode":"ip"}', '企微机器人，可选', 60, sysdate(), sysdate())
ON DUPLICATE KEY UPDATE config_value=VALUES(config_value), updated_at=sysdate();

-- 8. 钉钉（Demo 占位）
INSERT INTO app_config (config_category, config_key, config_value, description, sort_order, created_at, updated_at)
VALUES ('dingtalk', 'default', '{"webhook_url":"","secret":"","security_mode":"sign"}', '钉钉机器人，可选', 70, sysdate(), sysdate())
ON DUPLICATE KEY UPDATE config_value=VALUES(config_value), updated_at=sysdate();

-- 9. Git 仓库发现（MySQL 存储，与 Admin 共用）
INSERT INTO app_config (config_category, config_key, config_value, description, sort_order, created_at, updated_at)
VALUES ('git_source', 'default', '{"enabled":true,"repos_base_dir":"/app/data/repos_from_git","storage":{"type":"mysql","host":"mysql","port":3306,"user":"root","password":"root","database":"root_seeker"}}', 'Git 仓库发现，从 git_source_repos 表读取', 80, sysdate(), sysdate())
ON DUPLICATE KEY UPDATE config_value=VALUES(config_value), updated_at=sysdate();
