"""Git 仓库发现与存储的领域模型。"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any


@dataclass
class GitSourceCredential:
    """Git 平台凭证（域名、账号、密码/Token）。"""
    domain: str
    username: str
    password: str
    platform: str  # gitee | github | gitlab | codeup
    created_at: datetime | None = None


@dataclass
class GitSourceRepo:
    """从 Git 平台发现的仓库信息。"""
    id: str
    full_name: str  # 项目名（最后一段），用于展示
    full_path: str  # 完整路径（org/group/repo），用于 API、list_branches
    platform_id: str | None  # 平台返回的 ID（如 Codeup 的 id）
    git_url: str
    default_branch: str
    description: str | None
    selected_branches: list[str]
    enabled: bool
    local_dir: str | None
    last_sync_at: datetime | None
    created_at: datetime | None
    extra: dict[str, Any] = field(default_factory=dict)

    @property
    def service_name(self) -> str:
        return self.full_name.replace("/", "-")


@dataclass
class GitSourceData:
    """存储的完整数据结构。"""
    credential: GitSourceCredential | None
    repos: list[GitSourceRepo]
    updated_at: datetime | None


def detect_platform(domain: str) -> str:
    """根据域名推断平台类型。"""
    d = domain.lower().replace("www.", "")
    if "gitee.com" in d:
        return "gitee"
    if "github.com" in d:
        return "github"
    if "gitlab.com" in d or "gitlab." in d:
        return "gitlab"
    if "codeup.aliyun.com" in d or "openapi-rdc.aliyuncs.com" in d:
        return "codeup"
    return "generic"
