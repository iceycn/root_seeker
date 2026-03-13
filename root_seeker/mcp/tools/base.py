"""MCP 工具基类。"""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any, Dict

from root_seeker.mcp.protocol import ToolResult, ToolSchema


class BaseTool(ABC):
    """内部 MCP 工具抽象基类。"""

    @property
    @abstractmethod
    def name(self) -> str:
        """工具唯一标识。"""
        ...

    @property
    @abstractmethod
    def schema(self) -> ToolSchema:
        """工具 Schema（name, description, inputSchema）。"""
        ...

    @abstractmethod
    async def run(self, args: Dict[str, Any], context: Dict[str, Any] | None = None) -> ToolResult:
        """执行工具，返回 ToolResult。"""
        ...
