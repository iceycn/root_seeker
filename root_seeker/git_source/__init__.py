"""Git 仓库发现：根据域名+账号密码获取仓库列表，支持分支选择与定期同步。"""
from __future__ import annotations

from root_seeker.git_source.models import GitSourceCredential, GitSourceRepo, detect_platform
from root_seeker.git_source.service import GitSourceService
from root_seeker.git_source.storage import FileStorageBackend, MySQLStorageBackend, StorageBackend

__all__ = [
    "GitSourceCredential",
    "GitSourceRepo",
    "GitSourceService",
    "StorageBackend",
    "FileStorageBackend",
    "MySQLStorageBackend",
    "detect_platform",
]


def create_storage_from_config(storage_config: dict) -> StorageBackend:
    """根据配置创建存储后端（策略模式）。各项目维护自己的 config.yaml。"""
    stype = (storage_config.get("type") or "file").lower()
    if stype == "mysql":
        return MySQLStorageBackend(
            host=storage_config.get("host", "localhost"),
            port=int(storage_config.get("port", 3306)),
            user=storage_config.get("user", "root"),
            password=storage_config.get("password", ""),
            database=storage_config.get("database", "root_seeker"),
        )
    fp = storage_config.get("file_path", "data/git_source.json")
    if ".." in fp or "\0" in fp:
        raise ValueError("file_path 不允许包含路径遍历字符 (.. 或 \\0)")
    return FileStorageBackend(file_path=fp)
