-- 分析任务状态表：RootSeeker 解析任务状态同步到数据库
-- 状态：pending=待调度, parsing=解析中, parsed=解析完成, failed=解析失败
CREATE TABLE IF NOT EXISTS analysis_status (
    analysis_id VARCHAR(64) NOT NULL PRIMARY KEY COMMENT '分析任务ID',
    status VARCHAR(20) NOT NULL DEFAULT 'pending' COMMENT '状态: pending|parsing|parsed|failed',
    status_display VARCHAR(32) NULL COMMENT '展示用: 待调度|解析中|解析完成|解析失败',
    error TEXT NULL COMMENT '解析失败原因',
    service_name VARCHAR(255) NULL COMMENT '服务名，便于查询',
    created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
    INDEX idx_status (status),
    INDEX idx_service_name (service_name),
    INDEX idx_updated_at (updated_at)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci COMMENT='分析任务状态表';
