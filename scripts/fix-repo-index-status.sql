-- 修复 api-gateway 等仓库的 repo_index_status
-- 若禁用后状态未正确更新，可手动将 qdrant/zoekt 置为 0
-- 用法: mysql -h HOST -P PORT -u USER -p root_seeker < scripts/fix-repo-index-status.sql

-- 查看当前 api-gateway 状态
SELECT '=== 修复前 ===' as step;
SELECT service_name, qdrant_indexed, zoekt_indexed, updated_at 
FROM repo_index_status WHERE service_name = 'api-gateway';

-- 若需强制设为未索引（禁用后状态未刷新时）
INSERT INTO repo_index_status (service_name, qdrant_indexed, qdrant_indexing, qdrant_count, zoekt_indexed, zoekt_indexing)
VALUES ('api-gateway', 0, 0, 0, 0, 0)
ON DUPLICATE KEY UPDATE 
  qdrant_indexed = 0, qdrant_indexing = 0, qdrant_count = 0,
  zoekt_indexed = 0, zoekt_indexing = 0;

SELECT '=== 修复后 ===' as step;
SELECT service_name, qdrant_indexed, zoekt_indexed, updated_at 
FROM repo_index_status WHERE service_name = 'api-gateway';
