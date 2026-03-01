"""Git 平台获取器接口。"""
from __future__ import annotations

from typing import Any, Protocol

from root_seeker.git_source.models import GitSourceCredential

# 平台返回的原始结构（各平台字段不同）
RepoInfo = dict[str, Any]
BranchInfo = dict[str, Any]


class GitFetcher(Protocol):
    """Git 平台仓库与分支获取接口（策略模式）。"""

    def list_repos(self, credential: GitSourceCredential) -> list[RepoInfo]:
        """获取当前用户/账号下的所有仓库。"""
        ...

    def list_branches(
        self,
        credential: GitSourceCredential,
        owner: str,
        repo: str,
        search: str | None = None,
    ) -> list[BranchInfo]:
        """获取仓库分支列表，支持 search 过滤。"""
        ...
