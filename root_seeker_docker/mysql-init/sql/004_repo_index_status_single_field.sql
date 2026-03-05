-- 单字段状态：未索引|索引中|已索引|清理中，流转：未索引->索引中->已索引；已索引->清理中->未索引
ALTER TABLE repo_index_status
    ADD COLUMN qdrant_status VARCHAR(20) NOT NULL DEFAULT '未索引' COMMENT 'Qdrant状态：未索引/索引中/已索引/清理中',
    ADD COLUMN zoekt_status VARCHAR(20) NOT NULL DEFAULT '未索引' COMMENT 'Zoekt状态：未索引/索引中/已索引/清理中';

-- 迁移旧数据
UPDATE repo_index_status SET
    qdrant_status = CASE WHEN qdrant_indexing = 1 THEN '索引中' WHEN qdrant_indexed = 1 THEN '已索引' ELSE '未索引' END,
    zoekt_status = CASE WHEN zoekt_indexing = 1 THEN '索引中' WHEN zoekt_indexed = 1 THEN '已索引' ELSE '未索引' END;

-- 删除旧列
ALTER TABLE repo_index_status
    DROP COLUMN qdrant_indexed,
    DROP COLUMN qdrant_indexing,
    DROP COLUMN zoekt_indexed,
    DROP COLUMN zoekt_indexing;
