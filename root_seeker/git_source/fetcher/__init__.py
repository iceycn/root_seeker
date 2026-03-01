"""Git 平台仓库与分支获取。"""
from __future__ import annotations

from root_seeker.git_source.fetcher.base import GitFetcher
from root_seeker.git_source.fetcher.codeup import CodeupFetcher
from root_seeker.git_source.fetcher.gitee import GiteeFetcher
from root_seeker.git_source.fetcher.github import GitHubFetcher
from root_seeker.git_source.fetcher.gitlab import GitLabFetcher
from root_seeker.git_source.fetcher.registry import get_fetcher

__all__ = ["GitFetcher", "CodeupFetcher", "GiteeFetcher", "GitHubFetcher", "GitLabFetcher", "get_fetcher"]
