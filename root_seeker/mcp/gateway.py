from __future__ import annotations

import asyncio
import logging
from typing import Any, Dict, List

from root_seeker.config import McpConfig, McpServerConfig
from root_seeker.mcp.external_client import ExternalMcpSession, is_mcp_sdk_available
from root_seeker.mcp.protocol import ErrorCode, ToolSchema, ToolResult
from root_seeker.mcp.tools.base import BaseTool

logger = logging.getLogger(__name__)

DEFAULT_TOOL_TIMEOUT_SECONDS = 120


def _validate_args(schema: ToolSchema, args: Dict[str, Any]) -> str | None:
    """校验 args 是否符合 inputSchema，返回错误信息或 None。"""
    if not isinstance(args, dict):
        return "args 必须为对象"
    inp = schema.inputSchema or {}
    required = inp.get("required") or []
    for r in required:
        if r not in args or args[r] is None:
            return f"缺少必填参数: {r}"
    return None


class McpGateway:
    def __init__(self, config: McpConfig, tool_timeout_seconds: float = DEFAULT_TOOL_TIMEOUT_SECONDS):
        self._config = config
        self._internal_tools: Dict[str, BaseTool] = {}
        self._external_sessions: Dict[str, ExternalMcpSession] = {}
        self._external_tools: Dict[str, str] = {}  # prefixed_name -> server_id
        self._tool_timeout = tool_timeout_seconds

    def register_internal_tool(self, tool: BaseTool) -> None:
        if tool.name in self._internal_tools:
            logger.warning(f"[McpGateway] Overwriting internal tool: {tool.name}")
        self._internal_tools[tool.name] = tool
        logger.info(f"[McpGateway] Registered internal tool: {tool.name}")

    async def list_tools(self) -> List[ToolSchema]:
        result = [t.schema for t in self._internal_tools.values()]
        for sid, sess in self._external_sessions.items():
            try:
                tools = await sess.list_tools()
                result.extend(tools)
            except Exception as e:
                logger.warning(f"[McpGateway] list_tools from {sid} failed: {e}")
        return result

    async def call_tool(self, name: str, args: Dict[str, Any], context: Dict[str, Any] | None = None) -> ToolResult:
        if name in self._internal_tools:
            tool = self._internal_tools[name]
            err_msg = _validate_args(tool.schema, args)
            if err_msg:
                return ToolResult.error(err_msg, error_code=ErrorCode.INVALID_PARAMS)
            try:
                return await asyncio.wait_for(
                    tool.run(args, context),
                    timeout=self._tool_timeout,
                )
            except asyncio.TimeoutError:
                logger.error(f"[McpGateway] Tool timeout: {name}")
                return ToolResult.error(
                    f"Tool execution timeout after {self._tool_timeout}s",
                    error_code=ErrorCode.TOOL_TIMEOUT,
                )
            except Exception as e:
                logger.error(f"[McpGateway] Tool execution failed: {name}, error={e}", exc_info=True)
                return ToolResult.error(f"Tool execution failed: {str(e)}", error_code=ErrorCode.INTERNAL_ERROR)

        server_id = self._external_tools.get(name)
        if server_id and server_id in self._external_sessions:
            sess = self._external_sessions[server_id]
            return await sess.call_tool(name, args)

        return ToolResult.error(f"Tool not found: {name}", error_code=ErrorCode.TOOL_NOT_FOUND)

    async def startup(self) -> None:
        """加载并启动配置中的外部 MCP Server。"""
        if not self._config.servers:
            return
        if not is_mcp_sdk_available():
            logger.info("[McpGateway] MCP SDK 未安装，跳过外部 Server 加载。pip install mcp 可启用。")
            return
        for server_id, sc in self._config.servers.items():
            if not getattr(sc, "enabled", True):
                continue
            if not isinstance(sc, McpServerConfig):
                continue
            transport = getattr(sc, "transport", "stdio") or "stdio"
            if transport == "streamable-http":
                url = getattr(sc, "url", None)
                if not url:
                    logger.warning("[McpGateway] %s: streamable-http 需要 url，跳过", server_id)
                    continue
                sess = ExternalMcpSession(
                    server_id,
                    transport="streamable-http",
                    url=url,
                )
            else:
                command = getattr(sc, "command", "") or ""
                if not command:
                    logger.warning("[McpGateway] %s: stdio 需要 command，跳过", server_id)
                    continue
                sess = ExternalMcpSession(
                    server_id,
                    transport="stdio",
                    command=command,
                    args=getattr(sc, "args", []) or [],
                    env=getattr(sc, "env", {}) or {},
                )
            if await sess.connect():
                self._external_sessions[server_id] = sess
                for t in await sess.list_tools():
                    self._external_tools[t.name] = server_id
        if self._external_sessions:
            logger.info("[McpGateway] 已加载 %d 个外部 MCP Server: %s", len(self._external_sessions), list(self._external_sessions.keys()))

    async def shutdown(self) -> None:
        """断开所有外部 MCP Server。"""
        for sid, sess in list(self._external_sessions.items()):
            try:
                await sess.disconnect()
            except Exception as e:
                logger.warning("[McpGateway] shutdown %s: %s", sid, e)
        self._external_sessions.clear()
        self._external_tools.clear()
