"""阿里云 Codeup（云效）平台适配器。API: https://{domain}/oapi/v1/codeup"""
from __future__ import annotations

from typing import Any
from urllib.parse import quote

import httpx

from root_seeker.git_source.models import GitSourceCredential

# 云效官方 API 接入点（codeup.aliyun.com 会 302 重定向到登出页，必须用此域名）
CODUP_API_DOMAIN = "openapi-rdc.aliyuncs.com"


class CodeupFetcher:
    """
    阿里云 Codeup 仓库与分支获取。
    认证：x-yunxiao-token（个人访问令牌）。
    username 存 organizationId，password 存 Personal Access Token。
    domain 使用 openapi-rdc.aliyuncs.com（codeup.aliyun.com 会 302 重定向导致认证失败）。
    """

    def _base_url(self, credential: GitSourceCredential) -> str:
        d = (credential.domain or "").strip()
        if "openapi-rdc.aliyuncs.com" in d or "aliyuncs.com" in d:
            return f"https://{CODUP_API_DOMAIN}/oapi/v1/codeup"
        return f"https://{CODUP_API_DOMAIN}/oapi/v1/codeup"

    def _headers(self, credential: GitSourceCredential) -> dict[str, str]:
        return {"x-yunxiao-token": credential.password}

    def _check_auth_error(self, exc: Exception) -> None:
        """将 302 重定向到登出页等错误转为更友好的提示。"""
        msg = str(exc).lower()
        if "302" in str(exc) and ("logout" in msg or "relogin" in msg):
            raise ValueError(
                "凭证无效或已过期。请使用域名 openapi-rdc.aliyuncs.com，"
                "账号填组织 ID、密码填个人访问令牌（PAT）"
            ) from exc

    def list_repos(self, credential: GitSourceCredential) -> list[dict[str, Any]]:
        """获取当前组织下用户有权限的仓库列表。username 需为 organizationId。"""
        org_id = credential.username.strip()
        if not org_id:
            raise ValueError("Codeup 需要 organizationId，请将组织 ID 填入 username")
        base = self._base_url(credential)
        url = f"{base}/organizations/{org_id}/repositories"
        all_repos: list[dict] = []
        page = 1
        per_page = 100
        while True:
            try:
                r = httpx.get(
                    url,
                    headers=self._headers(credential),
                    params={"page": page, "perPage": per_page},
                    timeout=30,
                )
                r.raise_for_status()
            except Exception as e:
                self._check_auth_error(e)
                raise
            data = r.json()
            if not isinstance(data, list):
                break
            all_repos.extend(data)
            if len(data) < per_page:
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
        """获取仓库分支。repositoryId 可为数字 ID 或 path（如 owner/repo）。"""
        org_id = credential.username.strip()
        base = self._base_url(credential)
        repo_id = f"{owner}/{repo}"
        url = f"{base}/organizations/{org_id}/repositories/{quote(repo_id, safe='')}/branches"
        all_branches: list[dict] = []
        page = 1
        per_page = 100
        while True:
            params: dict[str, Any] = {"page": page, "perPage": per_page}
            if search:
                params["search"] = search
            r = httpx.get(
                url,
                headers=self._headers(credential),
                params=params,
                timeout=30,
            )
            r.raise_for_status()
            branches = r.json()
            if not isinstance(branches, list):
                break
            all_branches.extend(branches)
            if len(branches) < per_page:
                break
            page += 1
        return all_branches
