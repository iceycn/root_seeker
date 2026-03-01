"""Gitee 平台适配器。API: https://gitee.com/api/v5"""
from __future__ import annotations

from typing import Any

import httpx

from root_seeker.git_source.models import GitSourceCredential


class GiteeFetcher:
    """Gitee 仓库与分支获取。"""

    BASE = "https://gitee.com/api/v5"

    def list_repos(self, credential: GitSourceCredential) -> list[dict[str, Any]]:
        """获取当前用户仓库列表。password 可为账号密码或 Personal Access Token。"""
        url = f"{self.BASE}/user/repos"
        # Gitee 支持 access_token 或 Basic Auth
        auth = (credential.username, credential.password)
        params: dict[str, Any] = {"per_page": 100, "page": 1}
        all_repos: list[dict] = []
        while True:
            r = httpx.get(url, params=params, auth=auth, timeout=30)
            r.raise_for_status()
            repos = r.json()
            if not repos:
                break
            all_repos.extend(repos)
            if len(repos) < 100:
                break
            params["page"] = params.get("page", 1) + 1
        return all_repos

    def list_branches(
        self,
        credential: GitSourceCredential,
        owner: str,
        repo: str,
        search: str | None = None,
    ) -> list[dict[str, Any]]:
        """获取仓库分支，search 为关键词过滤。"""
        url = f"{self.BASE}/repos/{owner}/{repo}/branches"
        auth = (credential.username, credential.password)
        params = {"per_page": 100}
        r = httpx.get(url, params=params, auth=auth, timeout=30)
        r.raise_for_status()
        branches = r.json()
        if search:
            search_lower = search.lower()
            branches = [b for b in branches if search_lower in (b.get("name") or "").lower()]
        return branches
