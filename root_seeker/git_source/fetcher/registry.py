"""Git 平台获取器注册表。"""
from __future__ import annotations

from root_seeker.git_source.fetcher.base import GitFetcher
from root_seeker.git_source.fetcher.codeup import CodeupFetcher
from root_seeker.git_source.fetcher.gitee import GiteeFetcher
from root_seeker.git_source.fetcher.github import GitHubFetcher
from root_seeker.git_source.fetcher.gitlab import GitLabFetcher
from root_seeker.git_source.models import GitSourceCredential, detect_platform

_FETCHERS: dict[str, GitFetcher] = {
    "gitee": GiteeFetcher(),
    "github": GitHubFetcher(),
    "gitlab": GitLabFetcher(),
    "codeup": CodeupFetcher(),
}


def get_fetcher(credential: GitSourceCredential) -> GitFetcher:
    """根据凭证获取对应平台的 Fetcher。"""
    platform = credential.platform or detect_platform(credential.domain)
    fetcher = _FETCHERS.get(platform)
    if not fetcher:
        raise ValueError(f"不支持的 Git 平台: {platform}，支持: gitee, github, gitlab, codeup")
    return fetcher
