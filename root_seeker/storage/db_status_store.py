"""分析状态数据库同步：当 config_db 配置时，将状态写入 analysis_status 表。"""
from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any

from root_seeker.storage.status_store import AnalysisStatus

logger = logging.getLogger(__name__)

# 内部状态 -> 数据库状态（解析语义）
_STATUS_TO_DB = {
    "pending": ("pending", "待调度"),
    "running": ("parsing", "解析中"),
    "completed": ("parsed", "解析完成"),
    "failed": ("failed", "解析失败"),
}


def _map_status(status: str) -> tuple[str, str]:
    """返回 (db_status, status_display)"""
    return _STATUS_TO_DB.get(status, (status, status))


def save_status_to_db(
    *,
    host: str,
    port: int,
    user: str,
    password: str,
    database: str,
    status: AnalysisStatus,
    service_name: str | None = None,
) -> None:
    """将分析状态写入数据库。"""
    try:
        import pymysql
    except ImportError:
        logger.warning("[DbStatusStore] PyMySQL 未安装，跳过数据库状态同步")
        return
    db_status, status_display = _map_status(status.status)
    conn = None
    try:
        conn = pymysql.connect(
            host=host,
            port=port,
            user=user,
            password=password,
            database=database,
            charset="utf8mb4",
        )
        with conn.cursor() as cur:
            cur.execute(
                """
                INSERT INTO analysis_status (analysis_id, status, status_display, error, service_name, created_at, updated_at)
                VALUES (%s, %s, %s, %s, %s, %s, %s)
                ON DUPLICATE KEY UPDATE
                    status = VALUES(status),
                    status_display = VALUES(status_display),
                    error = VALUES(error),
                    service_name = COALESCE(VALUES(service_name), service_name),
                    updated_at = VALUES(updated_at)
                """,
                (
                    status.analysis_id,
                    db_status,
                    status_display,
                    status.error,
                    service_name,
                    status.created_at,
                    status.updated_at,
                ),
            )
        conn.commit()
        logger.debug(f"[DbStatusStore] 已同步状态到数据库，analysis_id={status.analysis_id}, status={db_status}")
    except Exception as e:
        logger.warning(f"[DbStatusStore] 同步状态到数据库失败: {e}")
        if conn:
            conn.rollback()
    finally:
        if conn:
            conn.close()
