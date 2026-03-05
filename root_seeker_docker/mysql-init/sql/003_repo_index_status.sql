-- 仓库索引状态表：存储 Qdrant/Zoekt 状态，由 RootSeeker 回调更新
CREATE TABLE IF NOT EXISTS repo_index_status (
    service_name VARCHAR(255) NOT NULL PRIMARY KEY COMMENT '服务名，与 git_source full_name.replace("/","-") 一致',
    qdrant_indexed TINYINT(1) NOT NULL DEFAULT 0 COMMENT 'Qdrant 是否已索引：0否 1是',
    qdrant_indexing TINYINT(1) NOT NULL DEFAULT 0 COMMENT 'Qdrant 是否索引中：0否 1是',
    qdrant_count INT NOT NULL DEFAULT 0 COMMENT 'Qdrant 向量点数',
    zoekt_indexed TINYINT(1) NOT NULL DEFAULT 0 COMMENT 'Zoekt 是否已索引：0否 1是',
    zoekt_indexing TINYINT(1) NOT NULL DEFAULT 0 COMMENT 'Zoekt 是否索引中：0否 1是',
    updated_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
    INDEX idx_updated_at (updated_at)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci COMMENT='仓库索引状态（由回调更新）';
