"""外部依赖识别工具测试。"""

from __future__ import annotations

import asyncio
import json

import pytest

from root_seeker.mcp.gateway import McpGateway
from root_seeker.mcp.tools.deps_external import (
    DepsDiffDeclaredVsResolvedTool,
    DepsParseExternalTool,
    DepsScanBinariesTool,
)
from root_seeker.mcp.tools.cmd import CmdRunBuildAnalysisTool
from root_seeker.config import McpConfig
from root_seeker.services.router import RepoCatalog, ServiceRouter
from root_seeker.config import RepoConfig


@pytest.fixture
def router():
    """带当前项目目录的 router。"""
    import os
    cwd = os.getcwd()
    catalog = RepoCatalog(repos=[
        RepoConfig(service_name="root-seeker", git_url="", local_dir=cwd),
    ])
    return ServiceRouter(catalog)


def test_deps_parse_external(router):
    """deps.parse_external 能解析 pyproject.toml。"""
    gw = McpGateway(McpConfig(), tool_timeout_seconds=10.0)
    gw.register_internal_tool(DepsParseExternalTool(router))
    result = asyncio.run(gw.call_tool("deps.parse_external", {"repo_id": "root-seeker"}))
    assert not result.isError
    text = result.content[0].text if result.content else ""
    data = json.loads(text)
    assert data.get("ecosystem") == "python"
    assert "direct_dependencies" in data
    assert len(data["direct_dependencies"]) > 0


def test_deps_parse_external_missing_repo(router):
    """缺少 repo_id 时返回错误。"""
    gw = McpGateway(McpConfig(), tool_timeout_seconds=10.0)
    gw.register_internal_tool(DepsParseExternalTool(router))
    result = asyncio.run(gw.call_tool("deps.parse_external", {}))
    assert result.isError
    assert "INVALID_PARAMS" in (result.errorCode or "")


def test_deps_diff_declared_vs_resolved():
    """deps.diff_declared_vs_resolved 能对比声明与解析。"""
    gw = McpGateway(McpConfig(), tool_timeout_seconds=10.0)
    gw.register_internal_tool(DepsDiffDeclaredVsResolvedTool())
    declared = {"direct_dependencies": [{"group_id": "a", "artifact_id": "b", "version": "1.0"}]}
    resolved = [{"group_id": "a", "artifact_id": "b", "version": "1.1"}]
    result = asyncio.run(gw.call_tool("deps.diff_declared_vs_resolved", {"declared": declared, "resolved": resolved}))
    assert not result.isError
    data = json.loads(result.content[0].text)
    assert "version_mismatches" in data


def test_deps_scan_binaries(router):
    """deps.scan_binaries 能扫描二进制依赖。"""
    gw = McpGateway(McpConfig(), tool_timeout_seconds=10.0)
    gw.register_internal_tool(DepsScanBinariesTool(router))
    result = asyncio.run(gw.call_tool("deps.scan_binaries", {"repo_id": "root-seeker"}))
    assert not result.isError
    data = json.loads(result.content[0].text)
    assert "binaries" in data
    assert "count" in data
    assert isinstance(data["binaries"], list)
