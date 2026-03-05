#!/usr/bin/env python3
"""
创建 analysis_status 表（含 repo_id 列）。
使用环境变量：MYSQL_HOST、MYSQL_PORT、MYSQL_USERNAME、MYSQL_PASSWORD、MYSQL_DATABASE
默认与 RootSeeker Admin 一致：localhost:3306, root/password, root_seeker
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

# 加载 .env
env_file = ROOT / ".env"
if env_file.exists():
    for line in env_file.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if line and not line.startswith("#") and "=" in line:
            k, v = line.split("=", 1)
            os.environ.setdefault(k.strip(), v.strip().strip('"').strip("'"))

host = os.environ.get("MYSQL_HOST", "localhost")
port = int(os.environ.get("MYSQL_PORT", "3306"))
user = os.environ.get("MYSQL_USERNAME", os.environ.get("MYSQL_USER", "root"))
password = os.environ.get("MYSQL_PASSWORD", "password")
database = os.environ.get("MYSQL_DATABASE", "root_seeker")

SQL = """
CREATE DATABASE IF NOT EXISTS `{database}` DEFAULT CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci;
USE `{database}`;

CREATE TABLE IF NOT EXISTS analysis_status (
    analysis_id VARCHAR(64) NOT NULL PRIMARY KEY COMMENT '分析任务ID',
    status VARCHAR(20) NOT NULL DEFAULT 'pending' COMMENT '状态: pending|parsing|parsed|failed',
    status_display VARCHAR(32) NULL COMMENT '展示用: 待调度|解析中|解析完成|解析失败',
    error TEXT NULL COMMENT '解析失败原因',
    service_name VARCHAR(255) NULL COMMENT '服务名，便于查询',
    repo_id VARCHAR(128) NULL COMMENT '关联的 git_source_repos.id',
    created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
    INDEX idx_status (status),
    INDEX idx_service_name (service_name),
    INDEX idx_repo_id (repo_id),
    INDEX idx_updated_at (updated_at)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci COMMENT='分析任务状态表';

CREATE TABLE IF NOT EXISTS repo_index_status (
    service_name VARCHAR(255) NOT NULL PRIMARY KEY COMMENT '服务名',
    qdrant_indexed TINYINT(1) NOT NULL DEFAULT 0,
    qdrant_indexing TINYINT(1) NOT NULL DEFAULT 0,
    qdrant_count INT NOT NULL DEFAULT 0,
    zoekt_indexed TINYINT(1) NOT NULL DEFAULT 0,
    zoekt_indexing TINYINT(1) NOT NULL DEFAULT 0,
    updated_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
    INDEX idx_updated_at (updated_at)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci COMMENT='仓库索引状态（由回调更新）';
""".format(database=database)


def main() -> None:
    try:
        import pymysql
    except ImportError:
        print("[ERROR] 请安装 PyMySQL: pip install pymysql")
        sys.exit(1)

    print(f"[INFO] 连接 MySQL {host}:{port} 数据库 {database} ...")
    try:
        conn = pymysql.connect(
            host=host,
            port=port,
            user=user,
            password=password,
            charset="utf8mb4",
        )
        with conn.cursor() as cur:
            for stmt in SQL.split(";"):
                stmt = stmt.strip()
                if stmt and not stmt.startswith("--"):
                    cur.execute(stmt)
        conn.commit()
        conn.close()
        print("[OK] analysis_status、repo_index_status 表已创建")
    except Exception as e:
        print(f"[FAIL] {e}")
        sys.exit(1)


if __name__ == "__main__":
    main()
