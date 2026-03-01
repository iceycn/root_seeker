"""MySQL 存储：持久化到数据库。需安装 PyMySQL: pip install root-seeker[mysql]"""
from __future__ import annotations

import json
from contextlib import contextmanager
from datetime import datetime, timezone
from typing import Any

from root_seeker.git_source.models import (
    GitSourceCredential,
    GitSourceData,
    GitSourceRepo,
)


def _get_pymysql():
    try:
        import pymysql
        return pymysql
    except ImportError as e:
        raise ImportError(
            "MySQL 存储需要安装 PyMySQL: pip install root-seeker[mysql] 或 pip install PyMySQL"
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
        conn.commit()
    finally:
        conn.close()


class MySQLStorageBackend:
    """MySQL 存储。"""

    def __init__(
        self,
        *,
        host: str = "localhost",
        port: int = 3306,
        user: str = "root",
        password: str = "",
        database: str = "root_seeker",
    ):
        self._host = host
        self._port = port
        self._user = user
        self._password = password
        self._database = database

    def _ensure_tables(self, conn: Any) -> None:
        with conn.cursor() as cur:
            cur.execute("""
                CREATE TABLE IF NOT EXISTS git_source_credential (
                    id INT PRIMARY KEY DEFAULT 1,
                    domain VARCHAR(255) NOT NULL,
                    username VARCHAR(255) NOT NULL,
                    password VARCHAR(512) NOT NULL,
                    platform VARCHAR(64) NOT NULL,
                    created_at DATETIME,
                    updated_at DATETIME
                )
            """)
            cur.execute("""
                CREATE TABLE IF NOT EXISTS git_source_repos (
                    id VARCHAR(128) PRIMARY KEY,
                    full_name VARCHAR(255) NOT NULL,
                    full_path VARCHAR(512),
                    platform_id VARCHAR(64),
                    git_url VARCHAR(512) NOT NULL,
                    default_branch VARCHAR(128) NOT NULL DEFAULT 'main',
                    description TEXT,
                    selected_branches JSON,
                    enabled TINYINT(1) NOT NULL DEFAULT 1,
                    local_dir VARCHAR(512),
                    last_sync_at DATETIME,
                    created_at DATETIME,
                    extra JSON
                )
            """)
            # 兼容旧表：若无 full_path 则添加
            try:
                cur.execute("ALTER TABLE git_source_repos ADD COLUMN full_path VARCHAR(512)")
            except Exception:
                pass
            try:
                cur.execute("ALTER TABLE git_source_repos ADD COLUMN platform_id VARCHAR(64)")
            except Exception:
                pass

    def load(self) -> GitSourceData:
        with _connect(
            self._host, self._port, self._user, self._password, self._database
        ) as conn:
            self._ensure_tables(conn)
            cred = None
            repos: list[GitSourceRepo] = []
            with conn.cursor() as cur:
                cur.execute("SELECT * FROM git_source_credential WHERE id=1")
                row = cur.fetchone()
                if row:
                    cred = GitSourceCredential(
                        domain=row["domain"],
                        username=row["username"],
                        password=row["password"],
                        platform=row["platform"],
                        created_at=row["created_at"],
                    )
                cur.execute("SELECT * FROM git_source_repos")
                for r in cur.fetchall():
                    branches = r["selected_branches"]
                    if isinstance(branches, str):
                        branches = json.loads(branches) if branches else []
                    extra = r["extra"]
                    if isinstance(extra, str):
                        extra = json.loads(extra) if extra else {}
                    full_name = r.get("full_name", "")
                    full_path = r.get("full_path") or full_name  # 兼容旧数据
                    platform_id = r.get("platform_id")
                    if platform_id is not None:
                        platform_id = str(platform_id)
                    repos.append(GitSourceRepo(
                        id=r["id"],
                        full_name=full_name if "/" not in full_name else full_name.split("/")[-1],
                        full_path=full_path,
                        platform_id=platform_id,
                        git_url=r["git_url"],
                        default_branch=r["default_branch"] or "main",
                        description=r["description"],
                        selected_branches=branches,
                        enabled=bool(r["enabled"]),
                        local_dir=r["local_dir"],
                        last_sync_at=r["last_sync_at"],
                        created_at=r["created_at"],
                        extra=extra,
                    ))
            return GitSourceData(credential=cred, repos=repos, updated_at=None)

    def save(self, data: GitSourceData) -> None:
        with _connect(
            self._host, self._port, self._user, self._password, self._database
        ) as conn:
            self._ensure_tables(conn)
            now = datetime.now(timezone.utc)
            with conn.cursor() as cur:
                if data.credential:
                    cur.execute("""
                        INSERT INTO git_source_credential
                        (id, domain, username, password, platform, created_at, updated_at)
                        VALUES (1, %s, %s, %s, %s, %s, %s)
                        ON DUPLICATE KEY UPDATE
                        domain=%s, username=%s, password=%s, platform=%s, updated_at=%s
                    """, (
                        data.credential.domain, data.credential.username, data.credential.password,
                        data.credential.platform, data.credential.created_at or now, now,
                        data.credential.domain, data.credential.username, data.credential.password,
                        data.credential.platform, now,
                    ))
                cur.execute("DELETE FROM git_source_repos")
                for r in data.repos:
                    cur.execute("""
                        INSERT INTO git_source_repos
                        (id, full_name, full_path, platform_id, git_url, default_branch, description, selected_branches,
                         enabled, local_dir, last_sync_at, created_at, extra)
                        VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                    """, (
                        r.id, r.full_name, r.full_path, r.platform_id, r.git_url, r.default_branch, r.description,
                        json.dumps(r.selected_branches), 1 if r.enabled else 0,
                        r.local_dir, r.last_sync_at, r.created_at or now,
                        json.dumps(r.extra),
                    ))

    def save_credential(self, credential: GitSourceCredential) -> None:
        data = self.load()
        data.credential = credential
        self.save(data)

    def save_repos(self, repos: list[GitSourceRepo]) -> None:
        data = self.load()
        data.repos = repos
        self.save(data)

    def update_repo(self, repo: GitSourceRepo) -> None:
        data = self.load()
        found = False
        for i, r in enumerate(data.repos):
            if r.id == repo.id:
                data.repos[i] = repo
                found = True
                break
        if not found:
            data.repos.append(repo)
        self.save(data)
