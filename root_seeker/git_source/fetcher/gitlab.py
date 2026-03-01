"""GitLab 平台适配器。API: https://gitlab.com/api/v4"""
from __future__ import annotations

from typing import Any

import httpx

from root_seeker.git_source.models import GitSourceCredential


class GitLabFetcher:
    """GitLab 仓库与分支获取。password 需为 Personal Access Token。"""

    def _base_url(self, domain: str) -> str:
        return f"https://{domain}/api/v4" if "://" not in domain else f"{domain.rstrip('/')}/api/v4"

    def _headers(self, credential: GitSourceCredential) -> dict[str, str]:
        return {"PRIVATE-TOKEN": credential.password}

    def list_repos(self, credential: GitSourceCredential) -> list[dict[str, Any]]:
        """获取当前用户有权限的仓库。"""
        base = self._base_url(credential.domain)
        url = f"{base}/projects"
        all_repos: list[dict] = []
        page = 1
        while True:
            r = httpx.get(
                url,
                headers=self._headers(credential),
                params={"membership": "true", "per_page": 100, "page": page},
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
        """获取仓库分支。GitLab 用 project_id，此处 owner/repo 需对应 path_with_namespace。"""
        base = self._base_url(credential.domain)
        # 先根据 path 查 project_id
        path = f"{owner}/{repo}"
        search_r = httpx.get(
            f"{base}/projects",
            headers=self._headers(credential),
            params={"search": path, "per_page": 5},
            timeout=30,
        )
        search_r.raise_for_status()
        projects = search_r.json()
        project_id = None
        for p in projects:
            if (p.get("path_with_namespace") or "").lower() == path.lower():
                project_id = p.get("id")
                break
        if not project_id:
            return []
        url = f"{base}/projects/{project_id}/repository/branches"
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
