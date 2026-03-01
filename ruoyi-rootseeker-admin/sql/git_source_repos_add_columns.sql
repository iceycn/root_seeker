-- ----------------------------
-- 已有 git_source_repos 表升级：添加 full_path、platform_id 列
-- 若表为旧版创建（无此两列），执行本脚本
-- 若列已存在会报错，可忽略
-- ----------------------------
ALTER TABLE git_source_repos ADD COLUMN full_path VARCHAR(512) COMMENT '完整路径（org/group/repo）' AFTER full_name;
ALTER TABLE git_source_repos ADD COLUMN platform_id VARCHAR(64) COMMENT '平台返回的ID' AFTER full_path;
