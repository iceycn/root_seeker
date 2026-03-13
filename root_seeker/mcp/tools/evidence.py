"""证据上下文类 MCP 工具：evidence.context_search。"""

from __future__ import annotations

import json
from typing import Any, Dict

from root_seeker.mcp.protocol import ToolResult, ToolSchema
from root_seeker.mcp.tools.base import BaseTool


class EvidenceContextSearchTool(BaseTool):
    """
    evidence.context_search：在已收集的证据上下文中搜索。
    由 AI 规划调用，优先从此工具查找证据，避免重复调用 code.search/correlation.get_info。
    """

    @property
    def name(self) -> str:
        return "evidence.context_search"

    @property
    def schema(self) -> ToolSchema:
        return ToolSchema(
            name=self.name,
            description="在本次分析已收集的证据上下文中搜索。优先使用此工具查找证据，若未命中再调用 code.search、correlation.get_info 等。",
            inputSchema={
                "type": "object",
                "properties": {
                    "query": {
                        "type": "string",
                        "description": "搜索关键词或证据需求描述，如类名、方法名、配置项、'第三方 API 错误响应' 等",
                    },
                },
                "required": ["query"],
            },
        )

    async def run(self, args: Dict[str, Any], context: Dict[str, Any] | None = None) -> ToolResult:
        query = args.get("query")
        if not query or not str(query).strip():
            return ToolResult.text(
                json.dumps({"found": False, "match_count": 0, "reason": "query 为空"}, ensure_ascii=False)
            )
        evidence_ctx = (context or {}).get("evidence_ctx")
        if evidence_ctx is None:
            return ToolResult.text(
                json.dumps(
                    {"found": False, "match_count": 0, "reason": "上下文尚未初始化或不在证据收集阶段"},
                    ensure_ascii=False,
                )
            )
        result = evidence_ctx.search(str(query).strip())
        return ToolResult.text(json.dumps(result, ensure_ascii=False))
