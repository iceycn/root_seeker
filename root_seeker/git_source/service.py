"""Git 仓库发现服务：获取、存储、同步。"""
from __future__ import annotations

import logging
import re
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from root_seeker.config import RepoConfig
from root_seeker.git_source.fetcher.registry import get_fetcher
from root_seeker.git_source.models import (
    GitSourceCredential,
    GitSourceRepo,
    detect_platform,
)
from root_seeker.git_source.storage.base import StorageBackend

logger = logging.getLogger(__name__)


def _project_name(full_path: str) -> str:
    """从完整路径提取项目名（最后一段）。"""
    if not full_path or "/" not in full_path:
        return full_path or ""
    return full_path.split("/")[-1]


def _safe_repo_dir_name(full_path: str) -> str:
    """将 full_path 转为安全的目录名，防止路径遍历。"""
    s = (full_path or "").replace("/", "-").replace("..", "").replace("\\", "-")
    return re.sub(r"[^\w\-.]", "-", s).strip("-") or "repo"


def _normalize_gitee_repo(raw: dict[str, Any], credential: GitSourceCredential) -> GitSourceRepo:
    full_path = raw.get("full_name") or raw.get("path_with_namespace") or ""
    platform_id = str(raw["id"]) if raw.get("id") is not None else None
    return GitSourceRepo(
        id=str(raw.get("id", full_path or uuid.uuid4().hex)),
        full_name=_project_name(full_path),
        full_path=full_path,
        platform_id=platform_id,
        git_url=raw.get("clone_url") or raw.get("ssh_url") or f"https://gitee.com/{full_path}.git",
        default_branch=raw.get("default_branch") or "master",
        description=raw.get("description"),
        selected_branches=[],
        enabled=False,
        local_dir=None,
        last_sync_at=None,
        created_at=datetime.now(timezone.utc),
        extra={"raw_id": raw.get("id")},
    )


def _normalize_github_repo(raw: dict[str, Any], credential: GitSourceCredential) -> GitSourceRepo:
    full_path = raw.get("full_name") or ""
    platform_id = str(raw["id"]) if raw.get("id") is not None else None
    return GitSourceRepo(
        id=str(raw.get("id", full_path or uuid.uuid4().hex)),
        full_name=_project_name(full_path),
        full_path=full_path,
        platform_id=platform_id,
        git_url=raw.get("clone_url") or raw.get("ssh_url") or "",
        default_branch=raw.get("default_branch") or "main",
        description=raw.get("description"),
        selected_branches=[],
        enabled=False,
        local_dir=None,
        last_sync_at=None,
        created_at=datetime.now(timezone.utc),
        extra={"raw_id": raw.get("id")},
    )


def _normalize_gitlab_repo(raw: dict[str, Any], credential: GitSourceCredential) -> GitSourceRepo:
    full_path = raw.get("path_with_namespace") or raw.get("name") or ""
    platform_id = str(raw["id"]) if raw.get("id") is not None else None
    return GitSourceRepo(
        id=str(raw.get("id", uuid.uuid4().hex)),
        full_name=_project_name(full_path),
        full_path=full_path,
        platform_id=platform_id,
        git_url=raw.get("http_url_to_repo") or raw.get("ssh_url_to_repo") or "",
        default_branch=raw.get("default_branch") or "main",
        description=raw.get("description"),
        selected_branches=[],
        enabled=False,
        local_dir=None,
        last_sync_at=None,
        created_at=datetime.now(timezone.utc),
        extra={"raw_id": raw.get("id")},
    )


def _normalize_codeup_repo(raw: dict[str, Any], credential: GitSourceCredential) -> GitSourceRepo:
    """Codeup ListRepositories 返回：pathWithNamespace、nameWithNamespace、webUrl 等。"""
    path_with_ns = raw.get("pathWithNamespace") or raw.get("path_with_namespace") or ""
    name_with_ns = raw.get("nameWithNamespace") or ""
    full_path = (path_with_ns or name_with_ns.replace(" / ", "/").replace(" ", "/").strip())
    if not full_path and raw.get("path"):
        full_path = raw.get("path", "")
    platform_id = str(raw["id"]) if raw.get("id") is not None else None
    git_url = raw.get("httpUrlToRepo") or raw.get("sshUrlToRepo") or raw.get("http_url_to_repo")
    if not git_url and full_path:
        git_url = f"https://codeup.aliyun.com/{full_path}.git"
    return GitSourceRepo(
        id=str(raw.get("id", full_path or uuid.uuid4().hex)),
        full_name=_project_name(full_path),
        full_path=full_path,
        platform_id=platform_id,
        git_url=git_url or "",
        default_branch=raw.get("defaultBranch") or raw.get("default_branch") or "master",
        description=raw.get("description"),
        selected_branches=[],
        enabled=False,
        local_dir=None,
        last_sync_at=None,
        created_at=datetime.now(timezone.utc),
        extra={"raw_id": raw.get("id")},
    )


_NORMALIZERS = {
    "gitee": _normalize_gitee_repo,
    "github": _normalize_github_repo,
    "gitlab": _normalize_gitlab_repo,
    "codeup": _normalize_codeup_repo,
}


class GitSourceService:
    """Git 仓库发现与存储服务。"""

    def __init__(
        self,
        storage: StorageBackend,
        repos_base_dir: str | Path = "data/repos_from_git",
    ):
        self._storage = storage
        self._repos_base = Path(repos_base_dir)

    def verify_credentials(
        self,
        domain: str,
        username: str,
        password: str,
        platform: str | None = None,
    ) -> tuple[bool, str]:
        """
        验证凭证是否有效（不保存）。返回 (成功, 消息)。
        """
        platform = platform or detect_platform(domain)
        if platform == "generic":
            platform = detect_platform(domain)
        if platform == "generic":
            return False, "无法识别平台类型，请手动选择 Gitee/GitHub/GitLab/Codeup"
        cred = GitSourceCredential(
            domain=domain.strip(),
            username=username.strip(),
            password=password,
            platform=platform,
            created_at=datetime.now(timezone.utc),
        )
        try:
            fetcher = get_fetcher(cred)
            raw_repos = fetcher.list_repos(cred)
            count = len(raw_repos) if isinstance(raw_repos, list) else 0
            return True, f"凭证有效，可访问 {count} 个仓库"
        except Exception as e:
            return False, str(e)

    def connect(
        self,
        domain: str,
        username: str,
        password: str,
        platform: str | None = None,
    ) -> list[GitSourceRepo]:
        """
        连接 Git 平台，获取仓库列表，保存凭证。
        返回标准化后的仓库列表（不含已存储的选择状态）。
        """
        platform = platform or detect_platform(domain)
        if platform == "generic":
            platform = detect_platform(domain)
        cred = GitSourceCredential(
            domain=domain.strip(),
            username=username.strip(),
            password=password,
            platform=platform,
            created_at=datetime.now(timezone.utc),
        )
        fetcher = get_fetcher(cred)
        raw_repos = fetcher.list_repos(cred)
        normalizer = _NORMALIZERS.get(platform, _normalize_gitee_repo)
        new_repos = [normalizer(r, cred) for r in raw_repos]

        # 合并已存储的仓库状态（selected_branches, enabled, local_dir）
        stored = self._storage.load()
        stored_by_full_path = {r.full_path: r for r in stored.repos}

        merged: list[GitSourceRepo] = []
        for nr in new_repos:
            existing = stored_by_full_path.get(nr.full_path)
            if existing:
                merged.append(GitSourceRepo(
                    id=nr.id,
                    full_name=nr.full_name,
                    full_path=nr.full_path,
                    platform_id=nr.platform_id,
                    git_url=nr.git_url,
                    default_branch=nr.default_branch,
                    description=nr.description,
                    selected_branches=existing.selected_branches,
                    enabled=existing.enabled,
                    local_dir=existing.local_dir,
                    last_sync_at=existing.last_sync_at,
                    created_at=existing.created_at,
                    extra=nr.extra,
                ))
            else:
                merged.append(nr)

        self._storage.save_credential(cred)
        self._storage.save_repos(merged)
        logger.info(f"[GitSourceService] 已连接 {domain}，获取 {len(merged)} 个仓库")
        return merged

    def list_repos(
        self,
        search: str | None = None,
        enabled_only: bool = False,
    ) -> list[GitSourceRepo]:
        """列出已存储的仓库，支持搜索与过滤。"""
        data = self._storage.load()
        repos = data.repos
        if search:
            s = search.lower()
            repos = [r for r in repos if s in r.full_name.lower() or s in r.full_path.lower() or s in (r.description or "").lower()]
        if enabled_only:
            repos = [r for r in repos if r.enabled]
        return repos

    def list_branches(
        self,
        full_path: str,
        search: str | None = None,
    ) -> list[dict[str, Any]]:
        """获取指定仓库的分支列表。full_path 为完整路径（org/group/repo）。"""
        data = self._storage.load()
        if not data.credential:
            raise ValueError("未配置 Git 凭证，请先调用 connect")
        owner, _, repo = full_path.partition("/")
        if not repo:
            raise ValueError(f"无效的仓库路径: {full_path}")
        fetcher = get_fetcher(data.credential)
        return fetcher.list_branches(data.credential, owner, repo, search=search)

    def select_branches(
        self,
        repo_id_or_name: str,
        branches: list[str],
        enabled: bool = True,
    ) -> GitSourceRepo | None:
        """为仓库选择要跟踪的分支并启用。repo_id_or_name 可为 id、full_path 或 full_name。"""
        data = self._storage.load()
        for r in data.repos:
            if r.id == repo_id_or_name or r.full_path == repo_id_or_name or r.full_name == repo_id_or_name:
                updated = GitSourceRepo(
                    id=r.id,
                    full_name=r.full_name,
                    full_path=r.full_path,
                    platform_id=r.platform_id,
                    git_url=r.git_url,
                    default_branch=r.default_branch,
                    description=r.description,
                    selected_branches=branches if branches else [r.default_branch],
                    enabled=enabled,
                    local_dir=r.local_dir or str(self._repos_base / _safe_repo_dir_name(r.full_path)),
                    last_sync_at=r.last_sync_at,
                    created_at=r.created_at,
                    extra=r.extra,
                )
                self._storage.update_repo(updated)
                return updated
        return None

    def get_enabled_repos_as_config(self) -> list[RepoConfig]:
        """将已启用的仓库转为 RepoConfig，供 periodic 同步使用。"""
        data = self._storage.load()
        base = self._repos_base.resolve()
        result: list[RepoConfig] = []
        for r in data.repos:
            if not r.enabled or not r.local_dir:
                continue
            try:
                local_path = Path(r.local_dir).resolve()
                base_prefix = str(base).rstrip("/") + "/"
                if local_path != base and not str(local_path).startswith(base_prefix):
                    logger.warning(f"[GitSourceService] 忽略非法 local_dir（不在 base 下）: {r.local_dir}")
                    continue
            except (OSError, ValueError):
                logger.warning(f"[GitSourceService] 忽略无效 local_dir: {r.local_dir}")
                continue
            primary_branch = (r.selected_branches or [r.default_branch])[0]
            result.append(RepoConfig(
                service_name=r.service_name,
                git_url=r.git_url,
                local_dir=r.local_dir,
                repo_aliases=[],
                language_hints=[],
            ))
        return result
