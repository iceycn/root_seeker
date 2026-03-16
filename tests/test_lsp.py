"""Headless LSP 工具测试。"""

from __future__ import annotations

import asyncio
import os

import pytest

from root_seeker.mcp.gateway import McpGateway
from root_seeker.mcp.tools.lsp import (
    LspDefinitionTool,
    LspDocumentSymbolsTool,
    LspStartTool,
    LspWorkspaceSymbolTool,
)
from root_seeker.config import McpConfig
from root_seeker.services.router import RepoCatalog, ServiceRouter
from root_seeker.config import RepoConfig


@pytest.fixture
def router():
    cwd = os.getcwd()
    catalog = RepoCatalog(repos=[
        RepoConfig(service_name="root-seeker", git_url="", local_dir=cwd),
    ])
    return ServiceRouter(catalog)


@pytest.mark.skipif(
    not __import__("shutil").which("pylsp"),
    reason="pylsp 未安装，跳过 LSP 测试",
)
def test_lsp_start_document_symbols(router):
    """lsp.start + lsp.document_symbols 能工作。pylsp 支持 document_symbols，不支持 workspace_symbol。
    必须在同一事件循环中调用，否则 LSP 子进程的 Future 会绑定到已关闭的 loop。"""
    import json

    async def run_both():
        gw = McpGateway(McpConfig(), tool_timeout_seconds=60.0)
        gw.register_internal_tool(LspStartTool(router))
        gw.register_internal_tool(LspDocumentSymbolsTool(router))

        result = await gw.call_tool("lsp.start", {"language": "python", "repo_id": "root-seeker"})
        assert not result.isError, result.content[0].text if result.content else ""

        result2 = await gw.call_tool("lsp.document_symbols", {
            "language": "python",
            "repo_id": "root-seeker",
            "file_path": "root_seeker/__init__.py",
        })
        return result2

    result2 = asyncio.run(run_both())
    assert not result2.isError
    data = json.loads(result2.content[0].text)
    assert isinstance(data, list)


def test_lsp_start_missing_repo(router):
    """缺少 repo_id 时返回错误。"""
    gw = McpGateway(McpConfig(), tool_timeout_seconds=10.0)
    gw.register_internal_tool(LspStartTool(router))
    result = asyncio.run(gw.call_tool("lsp.start", {"language": "python"}))
    assert result.isError
    assert "INVALID_PARAMS" in (result.errorCode or "")
