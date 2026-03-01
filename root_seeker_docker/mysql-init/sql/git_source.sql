-- ----------------------------
-- RootSeeker Git 仓库发现表（与 Python RootSeeker 共享）
-- 执行前需先创建数据库 root_seeker 并导入 ry_20250416.sql
-- ----------------------------

-- 凭证表
CREATE TABLE IF NOT EXISTS git_source_credential (
    id INT PRIMARY KEY DEFAULT 1,
    domain VARCHAR(255) NOT NULL COMMENT '平台域名',
    username VARCHAR(255) NOT NULL COMMENT '账号',
    password VARCHAR(512) NOT NULL COMMENT '密码/Token',
    platform VARCHAR(64) NOT NULL COMMENT 'gitee/github/gitlab/codeup',
    created_at DATETIME COMMENT '创建时间',
    updated_at DATETIME COMMENT '更新时间'
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COMMENT='Git 平台凭证';

-- 仓库表
CREATE TABLE IF NOT EXISTS git_source_repos (
    id VARCHAR(128) PRIMARY KEY COMMENT '仓库ID',
    full_name VARCHAR(255) NOT NULL COMMENT '项目名（最后一段，用于展示）',
    full_path VARCHAR(512) COMMENT '完整路径（org/group/repo，用于API）',
    platform_id VARCHAR(64) COMMENT '平台返回的ID',
    git_url VARCHAR(512) NOT NULL COMMENT 'clone URL',
    default_branch VARCHAR(128) NOT NULL DEFAULT 'main' COMMENT '默认分支',
    description TEXT COMMENT '描述',
    selected_branches JSON COMMENT '选中的分支列表',
    enabled TINYINT(1) NOT NULL DEFAULT 1 COMMENT '是否启用：0否 1是',
    local_dir VARCHAR(512) COMMENT '本地目录',
    last_sync_at DATETIME COMMENT '最后同步时间',
    created_at DATETIME COMMENT '创建时间',
    extra JSON COMMENT '扩展字段'
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COMMENT='Git 仓库';

-- 已有表升级：若表为旧版创建（无 full_path、platform_id），请执行：
--   mysql -u 用户名 -p root_seeker < sql/git_source_repos_add_columns.sql

-- RootSeeker 配置项（sys_config 表，需先导入 ry_20250416.sql）
-- 若已存在则跳过
INSERT INTO sys_config (config_name, config_key, config_value, config_type, create_by, create_time, remark)
SELECT 'RootSeeker 分析服务地址', 'root.seeker.baseUrl', 'http://localhost:8000', 'Y', 'admin', sysdate(), 'RootSeeker 服务 base URL，用于拉取仓库、同步等。默认 http://localhost:8000'
FROM DUAL WHERE NOT EXISTS (SELECT 1 FROM sys_config WHERE config_key = 'root.seeker.baseUrl');
