"""存储策略基类：统一接口。"""
from __future__ import annotations

from typing import Protocol

from root_seeker.git_source.models import GitSourceCredential, GitSourceData, GitSourceRepo


class StorageBackend(Protocol):
    """Git 仓库信息存储后端接口（策略模式）。"""

    def load(self) -> GitSourceData:
        """加载存储的数据。"""
        ...

    def save(self, data: GitSourceData) -> None:
        """保存数据。"""
        ...

    def save_credential(self, credential: GitSourceCredential) -> None:
        """保存凭证（可单独更新）。"""
        ...

    def save_repos(self, repos: list[GitSourceRepo]) -> None:
        """保存仓库列表（可单独更新）。"""
        ...

    def update_repo(self, repo: GitSourceRepo) -> None:
        """更新单个仓库（如分支选择、启用状态）。"""
        ...
