-- ----------------------------
-- 已有 git_source_repos 表升级：添加 full_path、platform_id 列
-- 若表为旧版创建（无此两列），执行本脚本
-- 若列已存在会报错，可忽略
-- ----------------------------
SET @col_full_path := (
  SELECT COUNT(*)
  FROM information_schema.COLUMNS
  WHERE TABLE_SCHEMA = DATABASE()
    AND TABLE_NAME = 'git_source_repos'
    AND COLUMN_NAME = 'full_path'
);
SET @sql_full_path := IF(
  @col_full_path = 0,
  'ALTER TABLE git_source_repos ADD COLUMN full_path VARCHAR(512) COMMENT ''完整路径（org/group/repo）'' AFTER full_name',
  'SELECT 1'
);
PREPARE stmt_full_path FROM @sql_full_path;
EXECUTE stmt_full_path;
DEALLOCATE PREPARE stmt_full_path;

SET @col_platform_id := (
  SELECT COUNT(*)
  FROM information_schema.COLUMNS
  WHERE TABLE_SCHEMA = DATABASE()
    AND TABLE_NAME = 'git_source_repos'
    AND COLUMN_NAME = 'platform_id'
);
SET @sql_platform_id := IF(
  @col_platform_id = 0,
  'ALTER TABLE git_source_repos ADD COLUMN platform_id VARCHAR(64) COMMENT ''平台返回的ID'' AFTER full_path',
  'SELECT 1'
);
PREPARE stmt_platform_id FROM @sql_platform_id;
EXECUTE stmt_platform_id;
DEALLOCATE PREPARE stmt_platform_id;
