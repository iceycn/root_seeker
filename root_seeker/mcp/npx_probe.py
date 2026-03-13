"""探测 npx 可用性，用于判断是否可加载 command: npx 的外部 MCP Server。"""

from __future__ import annotations

import logging
import shutil
import subprocess

logger = logging.getLogger(__name__)

_cached: bool | None = None


def probe_npx_available() -> bool:
    """
    探测 npx 是否可用。
    若可用则允许加载 command: npx 的 McpServerConfig（如 mcp-server-filesystem 等）。
    结果会缓存，避免重复探测。
    """
    global _cached
    if _cached is not None:
        return _cached
    try:
        path = shutil.which("npx")
        if path:
            r = subprocess.run(
                ["npx", "--version"],
                capture_output=True,
                text=True,
                timeout=5,
            )
            _cached = r.returncode == 0
        else:
            _cached = False
    except (subprocess.TimeoutExpired, FileNotFoundError, OSError) as e:
        logger.debug("[McpGateway] npx 探测失败: %s", e)
        _cached = False
    if _cached:
        logger.info("[McpGateway] npx 可用，可加载 command: npx 的外部 MCP Server")
    return _cached


def reset_npx_cache() -> None:
    """重置 npx 探测缓存（仅用于测试）。"""
    global _cached
    _cached = None
