"""从数据库加载配置。config_source=database 时使用。"""
from __future__ import annotations

import json
from contextlib import contextmanager
from typing import Any

from root_seeker.config import AppConfig


def _get_pymysql():
    try:
        import pymysql
        return pymysql
    except ImportError as e:
        raise ImportError(
            "数据库配置模式需要 PyMySQL: pip install root-seeker[mysql]"
        ) from e


@contextmanager
def _connect(host: str, port: int, user: str, password: str, database: str):
    pymysql = _get_pymysql()
    conn = pymysql.connect(
        host=host,
        port=port,
        user=user,
        password=password,
        database=database,
        charset="utf8mb4",
        cursorclass=pymysql.cursors.DictCursor,
    )
    try:
        yield conn
    finally:
        conn.close()


def load_config_from_db(
    host: str = "localhost",
    port: int = 3306,
    user: str = "root",
    password: str = "",
    database: str = "root_seeker",
) -> dict[str, Any]:
    """从 app_config 表加载配置，返回可合并到 yaml 的 dict。"""
    result: dict[str, Any] = {}
    with _connect(host, port, user, password, database) as conn:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT config_category, config_key, config_value FROM app_config "
                "WHERE config_category != 'system'"
            )
            for row in cur.fetchall():
                cat = row["config_category"]
                key = row["config_key"]
                val = row["config_value"]
                if not val:
                    continue
                try:
                    parsed = json.loads(val)
                except json.JSONDecodeError:
                    parsed = val
                if cat not in result:
                    result[cat] = {}
                if key == "default" or key == "":
                    if isinstance(parsed, dict):
                        result[cat] = parsed
                    else:
                        result[cat] = {"value": parsed}
                else:
                    if not isinstance(result[cat], dict):
                        result[cat] = {}
                    result[cat][key] = parsed
    return result


def get_config_source_from_db(
    host: str, port: int, user: str, password: str, database: str
) -> str:
    """获取 config_source 当前值。"""
    with _connect(host, port, user, password, database) as conn:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT config_value FROM app_config "
                "WHERE config_category='system' AND config_key='config_source'"
            )
            row = cur.fetchone()
            return (row["config_value"] or "file").strip().lower() if row else "file"


def save_config_to_db(
    host: str,
    port: int,
    user: str,
    password: str,
    database: str,
    config_category: str,
    config_value: dict[str, Any] | str,
    config_key: str = "default",
) -> None:
    """保存配置到 app_config 表。"""
    from datetime import datetime, timezone

    val = json.dumps(config_value, ensure_ascii=False) if isinstance(config_value, dict) else str(config_value)
    now = datetime.now(timezone.utc)
    with _connect(host, port, user, password, database) as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                INSERT INTO app_config (config_category, config_key, config_value, updated_at)
                VALUES (%s, %s, %s, %s)
                ON DUPLICATE KEY UPDATE config_value=%s, updated_at=%s
                """,
                (config_category, config_key, val, now, val, now),
            )
        conn.commit()


def set_config_source_in_db(
    host: str, port: int, user: str, password: str, database: str, source: str
) -> None:
    """设置 config_source。"""
    save_config_to_db(
        host, port, user, password, database,
        "system", source, config_key="config_source",
    )
