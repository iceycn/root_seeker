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


def _resolve_repo_id(cur, service_name: str | None) -> str | None:
    """根据 service_name 解析 git_source_repos.id，用于日志与仓库关联。"""
    if not service_name or not service_name.strip():
        return None
    try:
        # service_name 与 git_source 一致：full_name.replace("/", "-") 或 full_path.replace("/", "-")
        cur.execute(
            """
            SELECT id FROM git_source_repos
            WHERE enabled = 1
              AND (REPLACE(COALESCE(full_path, full_name), '/', '-') = %s OR full_name = %s)
            LIMIT 1
            """,
            (service_name.strip(), service_name.strip()),
        )
        row = cur.fetchone()
        return row[0] if row else None
    except Exception:
        return None


def save_status_to_db(
    *,
    host: str,
    port: int,
    user: str,
    password: str,
    database: str,
    status: AnalysisStatus,
    service_name: str | None = None,
    repo_id: str | None = None,
) -> None:
    """将分析状态写入数据库。repo_id 优先使用传入值，否则根据 service_name 解析，实现日志与仓库关联。"""
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
            if not repo_id:
                repo_id = _resolve_repo_id(cur, service_name)
            try:
                cur.execute(
                    """
                    INSERT INTO analysis_status (analysis_id, status, status_display, error, service_name, repo_id, created_at, updated_at)
                    VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
                    ON DUPLICATE KEY UPDATE
                        status = VALUES(status),
                        status_display = VALUES(status_display),
                        error = VALUES(error),
                        service_name = COALESCE(VALUES(service_name), service_name),
                        repo_id = COALESCE(VALUES(repo_id), repo_id),
                        updated_at = VALUES(updated_at)
                    """,
                    (
                        status.analysis_id,
                        db_status,
                        status_display,
                        status.error,
                        service_name,
                        repo_id,
                        status.created_at,
                        status.updated_at,
                    ),
                )
            except pymysql.OperationalError as e:
                if "Unknown column 'repo_id'" in str(e):
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
                else:
                    raise
        conn.commit()
        logger.debug(
            f"[DbStatusStore] 已同步状态到数据库，analysis_id={status.analysis_id}, status={db_status}, repo_id={repo_id}"
        )
    except Exception as e:
        logger.warning(f"[DbStatusStore] 同步状态到数据库失败: {e}")
        if conn:
            conn.rollback()
    finally:
        if conn:
            conn.close()
