#!/usr/bin/env python3
"""
执行数据库迁移。从 config.yaml 读取 config_db 连接信息并执行 scripts/migrations/*.sql
用法: python3 scripts/run-migration.py [--dry-run]
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

# 项目根目录
ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

def _strip_line_comments(sql: str) -> str:
    lines: list[str] = []
    for line in sql.splitlines():
        s = line.lstrip()
        if s.startswith("--"):
            continue
        lines.append(line)
    return "\n".join(lines)


def _split_sql_statements(sql: str) -> list[str]:
    sql = _strip_line_comments(sql)
    parts = sql.split(";")
    stmts: list[str] = []
    for part in parts:
        stmt = part.strip()
        if stmt:
            stmts.append(stmt)
    return stmts


def _migrate_repo_index_status_single_field(cur, database: str) -> None:
    def col_exists(col: str) -> bool:
        cur.execute(
            """
            SELECT COUNT(*)
            FROM information_schema.COLUMNS
            WHERE TABLE_SCHEMA=%s AND TABLE_NAME='repo_index_status' AND COLUMN_NAME=%s
            """,
            (database, col),
        )
        return (cur.fetchone() or (0,))[0] > 0

    if not col_exists("qdrant_status"):
        cur.execute(
            """
            ALTER TABLE repo_index_status
                ADD COLUMN qdrant_status VARCHAR(20) NOT NULL DEFAULT '未索引'
                COMMENT 'Qdrant状态：未索引/索引中/已索引/清理中'
            """
        )
    if not col_exists("zoekt_status"):
        cur.execute(
            """
            ALTER TABLE repo_index_status
                ADD COLUMN zoekt_status VARCHAR(20) NOT NULL DEFAULT '未索引'
                COMMENT 'Zoekt状态：未索引/索引中/已索引/清理中'
            """
        )

    if col_exists("qdrant_indexed") and col_exists("qdrant_indexing"):
        cur.execute(
            """
            UPDATE repo_index_status SET
                qdrant_status = CASE
                    WHEN qdrant_indexing = 1 THEN '索引中'
                    WHEN qdrant_indexed = 1 THEN '已索引'
                    ELSE '未索引'
                END
            """
        )
    if col_exists("zoekt_indexed") and col_exists("zoekt_indexing"):
        cur.execute(
            """
            UPDATE repo_index_status SET
                zoekt_status = CASE
                    WHEN zoekt_indexing = 1 THEN '索引中'
                    WHEN zoekt_indexed = 1 THEN '已索引'
                    ELSE '未索引'
                END
            """
        )

    for old_col in ("qdrant_indexed", "qdrant_indexing", "zoekt_indexed", "zoekt_indexing"):
        if col_exists(old_col):
            cur.execute(f"ALTER TABLE repo_index_status DROP COLUMN {old_col}")


def main() -> None:
    ap = argparse.ArgumentParser(description="执行数据库迁移")
    ap.add_argument("--dry-run", action="store_true", help="仅打印 SQL，不执行")
    args = ap.parse_args()

    import os
    os.chdir(ROOT)

    from root_seeker.config import get_config_db

    config_db = get_config_db()
    if not config_db:
        print("[ERROR] config_db 未配置，请在 config.yaml 中配置 config_db")
        sys.exit(1)

    host = os.environ.get("MYSQL_HOST") or config_db.get("host", "localhost")
    port = int(os.environ.get("MYSQL_PORT") or config_db.get("port", 3306))
    user = os.environ.get("MYSQL_USER") or config_db.get("user", "root")
    password = os.environ.get("MYSQL_PASSWORD") or config_db.get("password", "")
    database = os.environ.get("MYSQL_DATABASE") or config_db.get("database", "root_seeker")

    try:
        import pymysql
    except ImportError:
        print("[ERROR] 请安装 PyMySQL: pip install pymysql")
        sys.exit(1)

    ignore_error_codes = {1050, 1060, 1061, 1091}

    migrations_dir = ROOT / "scripts" / "migrations"
    if not migrations_dir.exists():
        print(f"[INFO] 迁移目录不存在: {migrations_dir}")
        sys.exit(0)

    sql_files = sorted(migrations_dir.glob("*.sql"))
    if not sql_files:
        print("[INFO] 无迁移文件")
        sys.exit(0)

    for fp in sql_files:
        sql = fp.read_text(encoding="utf-8").strip()
        if not sql:
            continue
        print(f"[RUN] {fp.name}")
        if args.dry_run:
            print(sql[:500] + ("..." if len(sql) > 500 else ""))
            continue
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
                if fp.name == "004_repo_index_status_single_field.sql":
                    _migrate_repo_index_status_single_field(cur, database)
                else:
                    for stmt in _split_sql_statements(sql):
                        try:
                            cur.execute(stmt)
                        except pymysql.MySQLError as e:
                            code = e.args[0] if getattr(e, "args", None) else None
                            if code in ignore_error_codes:
                                continue
                            raise
            conn.commit()
            conn.close()
            print(f"  [OK] {fp.name}")
        except Exception as e:
            print(f"  [FAIL] {fp.name}: {e}")
            sys.exit(1)

    print("[DONE] 迁移完成")


if __name__ == "__main__":
    main()
