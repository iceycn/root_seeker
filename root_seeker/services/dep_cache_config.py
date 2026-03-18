"""依赖缓存目录白名单配置。v3.0.0 显式配置，供 code.read、lsp_manager 等使用。"""

from __future__ import annotations

from pathlib import Path
from typing import List

_DEFAULT_ROOTS = [
    Path.home() / ".m2" / "repository",
    Path.home() / ".gradle" / "caches" / "modules" / "files",
]

_roots: List[Path] = []


def set_dep_cache_roots(paths: list[str] | None) -> None:
    """设置依赖缓存目录白名单。空或 None 时使用默认 ~/.m2、~/.gradle。"""
    global _roots
    if not paths:
        _roots = list(_DEFAULT_ROOTS)
        return
    _roots = [Path(p).expanduser().resolve() for p in paths if p]


def get_dep_cache_roots() -> list[Path]:
    """获取依赖缓存目录白名单。"""
    global _roots
    if not _roots:
        _roots = list(_DEFAULT_ROOTS)
    return _roots
