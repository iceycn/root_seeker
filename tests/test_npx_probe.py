"""npx 探测与外部 MCP 客户端单元测试。"""

from __future__ import annotations

import pytest

from root_seeker.mcp.npx_probe import probe_npx_available, reset_npx_cache


def test_probe_npx_available():
    """探测 npx 可用性（结果依赖环境）。"""
    reset_npx_cache()
    result = probe_npx_available()
    assert isinstance(result, bool)


def test_probe_npx_cached():
    """探测结果应被缓存。"""
    reset_npx_cache()
    r1 = probe_npx_available()
    r2 = probe_npx_available()
    assert r1 == r2
