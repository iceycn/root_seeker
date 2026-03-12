"""
外部 MCP Server 客户端：通过 stdio 或 streamable-http 连接，获取工具列表并执行调用。

依赖可选：pip install mcp。未安装时外部 Server 功能不可用。
"""

from __future__ import annotations

import asyncio
import logging
from typing import TYPE_CHECKING, Any

from root_seeker.mcp.protocol import ToolResult, ToolSchema
from root_seeker.mcp.npx_probe import probe_npx_available

logger = logging.getLogger(__name__)

_MCP_AVAILABLE = False
if TYPE_CHECKING:
    from mcp import ClientSession

try:
    from mcp import ClientSession
    from mcp.client.stdio import StdioServerParameters, stdio_client
    from mcp.client.streamable_http import streamablehttp_client

    _MCP_AVAILABLE = True
except ImportError:
    ClientSession = None  # type: ignore[misc, assignment]
    streamablehttp_client = None


def is_mcp_sdk_available() -> bool:
    """MCP Python SDK 是否已安装。"""
    return _MCP_AVAILABLE


def _resolve_env(env: dict[str, str]) -> dict[str, str]:
    """解析 ENV: 前缀的环境变量引用。"""
    resolved = {}
    for k, v in env.items():
        if isinstance(v, str) and v.startswith("ENV:"):
            key = v[4:].strip()
            resolved[k] = __import__("os").environ.get(key, "")
        else:
            resolved[k] = str(v)
    return resolved


def _mcp_tool_to_schema(tool: Any, prefix: str) -> ToolSchema:
    """将 MCP SDK 的 Tool 转为 ToolSchema。"""
    name = getattr(tool, "name", "") or ""
    if prefix:
        name = f"{prefix}.{name}"
    desc = getattr(tool, "description", None) or ""
    inp = getattr(tool, "inputSchema", None)
    if inp is None:
        inp = {}
    elif hasattr(inp, "model_dump"):
        inp = inp.model_dump()
    elif not isinstance(inp, dict):
        inp = {}
    return ToolSchema(name=name, description=desc, inputSchema=inp)


class ExternalMcpSession:
    """
    外部 MCP Server 会话封装。
    支持 stdio 与 streamable-http，负责连接生命周期与工具调用。
    """

    def __init__(self, server_id: str, transport: str, **kwargs: Any):
        self._server_id = server_id
        self._transport = transport
        self._kwargs = kwargs
        self._session: ClientSession | None = None
        self._stdio_context = None
        self._http_context = None
        self._tools_cache: list[ToolSchema] = []
        self._tool_name_to_original: dict[str, str] = {}

    async def connect(self) -> bool:
        """建立连接，返回是否成功。"""
        if not _MCP_AVAILABLE:
            logger.warning("[ExternalMcp] MCP SDK 未安装，跳过外部 Server: %s", self._server_id)
            return False

        if self._transport == "streamable-http":
            url = self._kwargs.get("url")
            if not url:
                logger.warning("[ExternalMcp] streamable-http 需要 url，跳过: %s", self._server_id)
                return False
            try:
                ctx = streamablehttp_client(url)
                read_stream, write_stream, _ = await ctx.__aenter__()
                self._http_context = ctx
                self._session = ClientSession(read_stream, write_stream)
                await self._session.__aenter__()
                await self._session.initialize()
                logger.info("[ExternalMcp] 已连接 streamable-http: %s", self._server_id)
                return True
            except Exception as e:
                logger.warning("[ExternalMcp] 连接失败 %s: %s", self._server_id, e, exc_info=True)
                return False

        command = self._kwargs.get("command", "")
        args = self._kwargs.get("args", [])
        env = _resolve_env(self._kwargs.get("env", {}))
        import os

        full_env = dict(os.environ)
        full_env.update(env)

        if "npx" in command.lower():
            if not probe_npx_available():
                logger.warning("[ExternalMcp] npx 不可用，跳过: %s", self._server_id)
                return False

        try:
            params = StdioServerParameters(command=command, args=args, env=full_env)
            ctx = stdio_client(params)
            read, write = await ctx.__aenter__()
            self._stdio_context = ctx
            self._session = ClientSession(read, write)
            await self._session.__aenter__()
            await self._session.initialize()
            logger.info("[ExternalMcp] 已连接 stdio: %s", self._server_id)
            return True
        except Exception as e:
            logger.warning("[ExternalMcp] 连接失败 %s: %s", self._server_id, e, exc_info=True)
            return False

    async def list_tools(self) -> list[ToolSchema]:
        """获取工具列表（带 server 前缀）。"""
        if not self._session:
            return []
        try:
            resp = await self._session.list_tools()
            tools = getattr(resp, "tools", []) or []
            result = []
            self._tool_name_to_original.clear()
            for t in tools:
                orig_name = getattr(t, "name", "") or ""
                schema = _mcp_tool_to_schema(t, self._server_id)
                result.append(schema)
                self._tool_name_to_original[schema.name] = orig_name
            self._tools_cache = result
            return result
        except Exception as e:
            logger.warning("[ExternalMcp] list_tools 失败 %s: %s", self._server_id, e)
            return self._tools_cache

    async def call_tool(self, prefixed_name: str, args: dict[str, Any]) -> ToolResult:
        """调用工具。prefixed_name 为带前缀的完整名。"""
        if not self._session:
            return ToolResult.error(
                f"External server {self._server_id} not connected",
                error_code="DEPENDENCY_UNAVAILABLE",
            )
        orig_name = self._tool_name_to_original.get(prefixed_name)
        if orig_name is None and prefixed_name.startswith(f"{self._server_id}."):
            orig_name = prefixed_name[len(self._server_id) + 1 :]
        if orig_name is None:
            orig_name = prefixed_name
        try:
            result = await asyncio.wait_for(
                self._session.call_tool(orig_name, arguments=args or {}),
                timeout=120,
            )
            content = getattr(result, "content", []) or []
            is_err = getattr(result, "isError", False)
            parts = []
            for c in content:
                text = getattr(c, "text", None) or ""
                if text:
                    parts.append(text)
            text = "\n".join(parts) if parts else ""
            if is_err:
                return ToolResult.error(text or "Tool returned error", error_code="INTERNAL_ERROR")
            return ToolResult.text(text)
        except asyncio.TimeoutError:
            return ToolResult.error("Tool execution timeout", error_code="TOOL_TIMEOUT")
        except Exception as e:
            logger.warning("[ExternalMcp] call_tool 失败 %s.%s: %s", self._server_id, orig_name, e)
            return ToolResult.error(str(e), error_code="INTERNAL_ERROR")

    async def disconnect(self) -> None:
        """断开连接。"""
        if self._session:
            try:
                await self._session.__aexit__(None, None, None)
            except Exception as e:
                logger.debug("[ExternalMcp] session close: %s", e)
            self._session = None
        if self._stdio_context:
            try:
                await self._stdio_context.__aexit__(None, None, None)
            except Exception:
                pass
            self._stdio_context = None
        if self._http_context:
            try:
                await self._http_context.__aexit__(None, None, None)
            except Exception:
                pass
            self._http_context = None
        logger.info("[ExternalMcp] 已断开: %s", self._server_id)
