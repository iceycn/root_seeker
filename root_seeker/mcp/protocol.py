from __future__ import annotations

from typing import Any, Dict, List, Optional, Literal
from pydantic import BaseModel, Field

class ToolInputSchema(BaseModel):
    type: Literal["object"] = "object"
    properties: Dict[str, Any]
    required: List[str] = Field(default_factory=list)

class ToolSchema(BaseModel):
    name: str
    description: str
    inputSchema: Dict[str, Any]

class ToolContent(BaseModel):
    type: Literal["text", "image", "resource"] = "text"
    text: str | None = None
    data: str | None = None
    mimeType: str | None = None
    resource: Any | None = None

class ToolResult(BaseModel):
    content: List[ToolContent]
    isError: bool = False
    errorCode: str | None = Field(default=None, description="TOOL_NOT_FOUND|INVALID_PARAMS|INTERNAL_ERROR|DEPENDENCY_UNAVAILABLE|TOOL_TIMEOUT")

    @classmethod
    def text(cls, text: str) -> ToolResult:
        return cls(content=[ToolContent(type="text", text=text)])

    @classmethod
    def error(cls, message: str, error_code: str | None = None) -> ToolResult:
        return cls(
            content=[ToolContent(type="text", text=message)],
            isError=True,
            errorCode=error_code,
        )

class ErrorCode:
    TOOL_NOT_FOUND = "TOOL_NOT_FOUND"
    INVALID_PARAMS = "INVALID_PARAMS"
    INTERNAL_ERROR = "INTERNAL_ERROR"
    DEPENDENCY_UNAVAILABLE = "DEPENDENCY_UNAVAILABLE"
    TOOL_TIMEOUT = "TOOL_TIMEOUT"  # 工具执行超时，便于 LLM/调用方区分重试策略
