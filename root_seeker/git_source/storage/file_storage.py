"""文件存储：JSON 格式持久化。"""
from __future__ import annotations

import json
import logging
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlparse

from root_seeker.git_source.models import (
    GitSourceCredential,
    GitSourceData,
    GitSourceRepo,
)


def _serialize_dt(dt: datetime | None) -> str | None:
    return dt.isoformat() if dt else None


def _deserialize_dt(s: str | None) -> datetime | None:
    if not s:
        return None
    try:
        return datetime.fromisoformat(s.replace("Z", "+00:00"))
    except Exception:
        return None


def _repo_to_dict(r: GitSourceRepo) -> dict:
    def _normalize_git_url_for_storage(url: str) -> str:
        s = (url or "").strip()
        if not s:
            return s
        if s.startswith("http://") or s.startswith("https://"):
            return s
        if s.startswith("ssh://"):
            parsed = urlparse(s)
            if parsed.hostname and parsed.path:
                path = parsed.path.lstrip("/")
                return f"https://{parsed.hostname}/{path}"
            return s
        if "@" in s and ":" in s and "://" not in s:
            host = s.split("@", 1)[1].split(":", 1)[0]
            path = s.split(":", 1)[1].lstrip("/")
            if host and path:
                return f"https://{host}/{path}"
        return s
    return {
        "id": r.id,
        "full_name": r.full_name,
        "full_path": r.full_path,
        "platform_id": r.platform_id,
        "git_url": _normalize_git_url_for_storage(r.git_url),
        "default_branch": r.default_branch,
        "description": r.description,
        "selected_branches": r.selected_branches,
        "enabled": r.enabled,
        "local_dir": r.local_dir,
        "last_sync_at": _serialize_dt(r.last_sync_at),
        "created_at": _serialize_dt(r.created_at),
        "extra": r.extra,
    }


def _dict_to_repo(d: dict) -> GitSourceRepo:
    full_path = d.get("full_path") or d.get("full_name", "")
    full_name = d.get("full_name", "")
    if full_path and "/" in full_path and "/" not in full_name:
        full_name = full_name or full_path.split("/")[-1]
    elif full_path and "/" in full_path:
        full_name = full_path.split("/")[-1]
    return GitSourceRepo(
        id=d.get("id", ""),
        full_name=full_name,
        full_path=full_path,
        platform_id=d.get("platform_id"),
        git_url=d.get("git_url", ""),
        default_branch=d.get("default_branch", "main"),
        description=d.get("description"),
        selected_branches=list(d.get("selected_branches", [])),
        enabled=bool(d.get("enabled", True)),
        local_dir=d.get("local_dir"),
        last_sync_at=_deserialize_dt(d.get("last_sync_at")),
        created_at=_deserialize_dt(d.get("created_at")),
        extra=dict(d.get("extra", {})),
    )


def _credential_to_dict(c: GitSourceCredential | None) -> dict | None:
    if not c:
        return None
    return {
        "domain": c.domain,
        "username": c.username,
        "password": c.password,
        "platform": c.platform,
        "clone_protocol": getattr(c, "clone_protocol", "https"),
        "created_at": _serialize_dt(c.created_at),
    }


def _dict_to_credential(d: dict | None) -> GitSourceCredential | None:
    if not d:
        return None
    return GitSourceCredential(
        domain=d.get("domain", ""),
        username=d.get("username", ""),
        password=d.get("password", ""),
        platform=d.get("platform", "generic"),
        clone_protocol=d.get("clone_protocol", "https") or "https",
        created_at=_deserialize_dt(d.get("created_at")),
    )


class FileStorageBackend:
    """JSON 文件存储。"""

    def __init__(self, file_path: str | Path):
        self._path = Path(file_path)

    def load(self) -> GitSourceData:
        if not self._path.exists():
            return GitSourceData(credential=None, repos=[], updated_at=None)
        try:
            raw = json.loads(self._path.read_text(encoding="utf-8"))
        except Exception as e:
            logging.getLogger(__name__).warning(
                "[FileStorage] 加载失败，返回空数据: path=%s, error=%s",
                self._path,
                e,
            )
            return GitSourceData(credential=None, repos=[], updated_at=None)
        cred = _dict_to_credential(raw.get("credential"))
        repos = [_dict_to_repo(r) for r in raw.get("repos", [])]
        updated = _deserialize_dt(raw.get("updated_at"))
        return GitSourceData(credential=cred, repos=repos, updated_at=updated)

    def save(self, data: GitSourceData) -> None:
        self._path.parent.mkdir(parents=True, exist_ok=True)
        now = datetime.now(timezone.utc)
        raw = {
            "credential": _credential_to_dict(data.credential),
            "repos": [_repo_to_dict(r) for r in data.repos],
            "updated_at": now.isoformat(),
        }
        self._path.write_text(json.dumps(raw, ensure_ascii=False, indent=2), encoding="utf-8")

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
        for i, r in enumerate(data.repos):
            if r.id == repo.id:
                data.repos[i] = repo
                self.save(data)
                return
        data.repos.append(repo)
        self.save(data)
