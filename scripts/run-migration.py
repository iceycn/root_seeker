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
                for stmt in sql.split(";"):
                    stmt = stmt.strip()
                    if stmt and not stmt.startswith("--"):
                        cur.execute(stmt)
            conn.commit()
            conn.close()
            print(f"  [OK] {fp.name}")
        except Exception as e:
            print(f"  [FAIL] {fp.name}: {e}")
            sys.exit(1)

    print("[DONE] 迁移完成")


if __name__ == "__main__":
    main()
