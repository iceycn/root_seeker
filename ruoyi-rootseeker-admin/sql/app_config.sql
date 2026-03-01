-- ----------------------------
-- RootSeeker 应用配置表（需在 root_seeker 库执行，支持数据库模式，与 config.yaml 二选一）
-- config_source=file 时用 config.yaml；config_source=database 时从此表读取
-- ----------------------------

CREATE TABLE IF NOT EXISTS app_config (
    id BIGINT PRIMARY KEY AUTO_INCREMENT COMMENT '主键',
    config_category VARCHAR(64) NOT NULL COMMENT '配置分类：system, llm, embedding, qdrant, aliyun_sls, wecom, dingtalk, zoekt 等',
    config_key VARCHAR(128) NOT NULL DEFAULT 'default' COMMENT '子键，default 表示主配置块',
    config_value TEXT COMMENT '配置值，JSON 或字符串',
    description VARCHAR(255) COMMENT '说明',
    sort_order INT DEFAULT 0 COMMENT '排序',
    created_at DATETIME COMMENT '创建时间',
    updated_at DATETIME COMMENT '更新时间',
    UNIQUE KEY uk_category_key (config_category, config_key)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COMMENT='RootSeeker 应用配置';

-- 系统级：配置来源开关（file=配置文件, database=数据库）
INSERT INTO app_config (config_category, config_key, config_value, description, sort_order, created_at, updated_at)
SELECT 'system', 'config_source', 'file', '配置来源：file=config.yaml，database=数据库', 0, sysdate(), sysdate()
FROM DUAL WHERE NOT EXISTS (SELECT 1 FROM app_config WHERE config_category='system' AND config_key='config_source');
