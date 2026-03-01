"""GitHub 平台适配器。API: https://api.github.com"""
from __future__ import annotations

from typing import Any

import httpx

from root_seeker.git_source.models import GitSourceCredential


class GitHubFetcher:
    """GitHub 仓库与分支获取。password 需为 Personal Access Token。"""

    BASE = "https://api.github.com"

    def _headers(self, credential: GitSourceCredential) -> dict[str, str]:
        return {
            "Authorization": f"Bearer {credential.password}",
            "Accept": "application/vnd.github.v3+json",
        }

    def list_repos(self, credential: GitSourceCredential) -> list[dict[str, Any]]:
        """获取当前用户仓库列表。"""
        url = f"{self.BASE}/user/repos"
        all_repos: list[dict] = []
        page = 1
        while True:
            r = httpx.get(
                url,
                headers=self._headers(credential),
                params={"per_page": 100, "page": page},
                timeout=30,
            )
            r.raise_for_status()
            repos = r.json()
            if not repos:
                break
            all_repos.extend(repos)
            if len(repos) < 100:
                break
            page += 1
        return all_repos

    def list_branches(
        self,
        credential: GitSourceCredential,
        owner: str,
        repo: str,
        search: str | None = None,
    ) -> list[dict[str, Any]]:
        """获取仓库分支。"""
        url = f"{self.BASE}/repos/{owner}/{repo}/branches"
        r = httpx.get(
            url,
            headers=self._headers(credential),
            params={"per_page": 100},
            timeout=30,
        )
        r.raise_for_status()
        branches = r.json()
        if search:
            search_lower = search.lower()
            branches = [b for b in branches if search_lower in (b.get("name") or "").lower()]
        return branches
