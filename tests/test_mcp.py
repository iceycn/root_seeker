"""MCP 网关与工具单元测试。"""

from __future__ import annotations

import asyncio

import pytest

from root_seeker.mcp.gateway import McpGateway
from root_seeker.mcp.protocol import ErrorCode, ToolResult, ToolSchema
from root_seeker.mcp.tools.base import BaseTool
from root_seeker.config import McpConfig


class _MockTool(BaseTool):
    """用于测试的 Mock 工具。"""

    def __init__(self, name: str = "mock.tool", required: list[str] | None = None):
        self._name = name
        self._required = required or []

    @property
    def name(self) -> str:
        return self._name

    @property
    def schema(self) -> ToolSchema:
        return ToolSchema(
            name=self._name,
            description="Mock tool for testing",
            inputSchema={"type": "object", "properties": {"x": {"type": "string"}}, "required": self._required},
        )

    async def run(self, args, context=None):
        return ToolResult.text(f"ok:{args.get('x', '')}")


@pytest.fixture
def gateway():
    return McpGateway(McpConfig(), tool_timeout_seconds=5.0)


def test_register_and_list_tools(gateway):
    gateway.register_internal_tool(_MockTool("tool.a"))
    gateway.register_internal_tool(_MockTool("tool.b"))
    tools = asyncio.run(gateway.list_tools())
    assert len(tools) == 2
    names = {t.name for t in tools}
    assert "tool.a" in names
    assert "tool.b" in names


def test_call_tool_success(gateway):
    gateway.register_internal_tool(_MockTool("test.tool", required=[]))
    result = asyncio.run(gateway.call_tool("test.tool", {"x": "hello"}))
    assert not result.isError
    assert len(result.content) == 1
    assert result.content[0].text == "ok:hello"


def test_call_tool_not_found(gateway):
    result = asyncio.run(gateway.call_tool("nonexistent", {}))
    assert result.isError
    assert result.errorCode == ErrorCode.TOOL_NOT_FOUND
    assert "not found" in (result.content[0].text or "").lower()


def test_call_tool_invalid_params(gateway):
    gateway.register_internal_tool(_MockTool("req.tool", required=["x"]))
    result = asyncio.run(gateway.call_tool("req.tool", {}))
    assert result.isError
    assert result.errorCode == ErrorCode.INVALID_PARAMS
    assert "缺少" in (result.content[0].text or "") or "x" in (result.content[0].text or "")


def test_call_tool_timeout_returns_tool_timeout_error_code():
    """超时应返回 TOOL_TIMEOUT 错误码，便于调用方区分重试策略。"""
    gw = McpGateway(McpConfig(), tool_timeout_seconds=0.05)

    class SlowTool(BaseTool):
        @property
        def name(self) -> str:
            return "slow.tool"

        @property
        def schema(self) -> ToolSchema:
            return ToolSchema(
                name="slow.tool",
                description="x",
                inputSchema={"type": "object", "required": []},
            )

        async def run(self, args, context=None):
            await asyncio.sleep(1.0)
            return ToolResult.text("done")

    gw.register_internal_tool(SlowTool())
    result = asyncio.run(gw.call_tool("slow.tool", {}))
    assert result.isError
    assert result.errorCode == ErrorCode.TOOL_TIMEOUT
    assert "timeout" in (result.content[0].text or "").lower()


def test_gateway_startup_shutdown_with_empty_servers():
    """无外部 Server 配置时，startup/shutdown 应正常完成。"""
    import asyncio

    from root_seeker.config import McpConfig
    from root_seeker.mcp.gateway import McpGateway

    gw = McpGateway(McpConfig(servers={}))
    asyncio.run(gw.startup())
    asyncio.run(gw.shutdown())


def test_call_tool_context_passthrough(gateway):
    async def _run(args, context=None):
        trace = (context or {}).get("trace_id", "?")
        return ToolResult.text(f"trace={trace}")

    class CtxTool(BaseTool):
        @property
        def name(self) -> str:
            return "ctx.tool"

        @property
        def schema(self) -> ToolSchema:
            return ToolSchema(
                name="ctx.tool",
                description="x",
                inputSchema={"type": "object", "required": []},
            )

        async def run(self, args, context=None):
            return await _run(args, context)

    gateway.register_internal_tool(CtxTool())
    result = asyncio.run(gateway.call_tool("ctx.tool", {}, context={"trace_id": "abc123"}))
    assert not result.isError
    assert "trace=abc123" in (result.content[0].text or "")
