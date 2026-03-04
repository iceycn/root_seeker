-- 为 analysis_status 添加 repo_id，关联 git_source_repos，便于日志与仓库关联
-- 若列已存在会报错，可忽略
ALTER TABLE analysis_status ADD COLUMN repo_id VARCHAR(128) NULL COMMENT '关联的 git_source_repos.id' AFTER service_name;
CREATE INDEX idx_repo_id ON analysis_status (repo_id);
