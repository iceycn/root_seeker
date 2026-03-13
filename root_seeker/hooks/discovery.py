"""
Hook 脚本发现与缓存。
"""

from __future__ import annotations

import logging
import os
import platform
from pathlib import Path
from typing import Literal

from root_seeker.hooks.types import HOOK_NAMES

logger = logging.getLogger(__name__)
# 启用时输出发现过程日志
_DEBUG_HOOKS = os.environ.get("DEBUG_HOOKS", "").lower() == "true"

HookName = Literal["AnalysisStart", "AnalysisComplete", "PreToolUse", "PostToolUse"]

# 默认全局 hooks 目录
DEFAULT_GLOBAL_HOOKS_DIR = Path.home() / ".rootseek" / "hooks"


def get_all_hooks_dirs(extra_dirs: list[str] | None = None) -> list[Path]:
    """
    获取所有 hooks 目录。
    顺序：extra_dirs（config）→ 全局 ~/.rootseek/hooks
    """
    dirs: list[Path] = []
    if extra_dirs:
        for d in extra_dirs:
            p = Path(os.path.expanduser(d)).resolve()
            if p.is_dir():
                dirs.append(p)
            else:
                logger.debug("[Hooks] 目录不存在，跳过: %s", p)
    if DEFAULT_GLOBAL_HOOKS_DIR.is_dir():
        dirs.append(DEFAULT_GLOBAL_HOOKS_DIR)
    return dirs


def _find_unix_hook(hook_name: HookName, hooks_dir: Path) -> Path | None:
    """Unix：查找可执行文件（无扩展名）。"""
    candidate = hooks_dir / hook_name
    try:
        if candidate.is_file() and os.access(candidate, os.X_OK):
            return candidate
    except OSError as e:
        logger.debug("[Hooks] 发现错误 %s @ %s: %s", hook_name, candidate, e)
    return None


def _find_windows_hook(hook_name: HookName, hooks_dir: Path) -> Path | None:
    """Windows：查找 .ps1 文件。"""
    candidate = hooks_dir / f"{hook_name}.ps1"
    try:
        if candidate.is_file():
            return candidate
    except OSError as e:
        logger.debug("[Hooks] 发现错误 %s @ %s: %s", hook_name, candidate, e)
    return None


def find_hook_in_dir(hook_name: HookName, hooks_dir: Path) -> Path | None:
    """在指定目录查找 hook 脚本。"""
    if hook_name not in HOOK_NAMES:
        return None
    if platform.system() == "Windows":
        return _find_windows_hook(hook_name, hooks_dir)
    return _find_unix_hook(hook_name, hooks_dir)


class HookDiscoveryCache:
    """
    缓存 hook 脚本路径，避免重复扫描。
    """

    def __init__(self, extra_dirs: list[str] | None = None):
        self._extra_dirs = extra_dirs or []
        self._cache: dict[HookName, list[Path]] = {}
        self._scanning: dict[HookName, list[Path] | None] = {}  # 并发去重

    def invalidate_all(self) -> None:
        """清空缓存。"""
        n = len(self._cache)
        self._cache.clear()
        if _DEBUG_HOOKS:
            logger.debug("[HookCache] invalidated %d entries", n)

    def get(self, hook_name: HookName) -> list[Path]:
        """获取 hook 脚本路径列表，命中缓存则直接返回。"""
        if hook_name in self._cache:
            if _DEBUG_HOOKS:
                logger.debug("[HookCache] cache hit for %s: %d scripts", hook_name, len(self._cache[hook_name]))
            return self._cache[hook_name]
        if _DEBUG_HOOKS:
            logger.debug("[HookCache] cache miss for %s, scanning...", hook_name)
        scripts = self._scan(hook_name)
        self._cache[hook_name] = scripts
        if _DEBUG_HOOKS:
            logger.debug("[HookCache] found %d scripts for %s", len(scripts), hook_name)
        return scripts

    def _scan(self, hook_name: HookName) -> list[Path]:
        """扫描所有目录。扫描异常时返回空，不中断系统。"""
        try:
            dirs = get_all_hooks_dirs(self._extra_dirs)
            scripts: list[Path] = []
            for d in dirs:
                try:
                    found = find_hook_in_dir(hook_name, d)
                    if found:
                        scripts.append(found)
                except OSError as e:
                    logger.debug("[HookDiscoveryCache] 扫描目录 %s 失败: %s", d, e)
            return scripts
        except Exception as e:
            logger.warning("[HookDiscoveryCache] 扫描 %s 失败: %s", hook_name, e)
            return []

    def has_hook(self, hook_name: HookName) -> bool:
        """是否存在该 hook 的脚本。"""
        return len(self.get(hook_name)) > 0
