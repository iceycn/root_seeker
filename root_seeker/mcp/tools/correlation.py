"""关联信息类 MCP 工具：correlation.get_info。"""

from __future__ import annotations

import json
from typing import Any, Dict

from root_seeker.domain import NormalizedErrorEvent
from root_seeker.mcp.protocol import ToolResult, ToolSchema
from root_seeker.mcp.tools.base import BaseTool
from root_seeker.services.enricher import LogEnricher


class CorrelationInfoTool(BaseTool):
    """correlation.get_info：根据错误事件查询关联日志（含 trace_id/request_id 调用链）。"""

    def __init__(self, enricher: LogEnricher):
        self._enricher = enricher

    @property
    def name(self) -> str:
        return "correlation.get_info"

    @property
    def schema(self) -> ToolSchema:
        return ToolSchema(
            name=self.name,
            description="根据 service_name、error_log、query_key 查询关联日志（含调用链 trace_id/request_id）。",
            inputSchema={
                "type": "object",
                "properties": {
                    "service_name": {"type": "string", "description": "服务名"},
                    "error_log": {"type": "string", "description": "错误日志内容"},
                    "query_key": {"type": "string", "description": "可选，SQL 模板 key，默认 default_error_context"},
                },
                "required": ["service_name", "error_log"],
            },
        )

    async def run(self, args: Dict[str, Any], context: Dict[str, Any] | None = None) -> ToolResult:
        service_name = args.get("service_name")
        error_log = args.get("error_log")
        query_key = args.get("query_key") or "default_error_context"

        if not service_name or not error_log:
            return ToolResult.error("缺少必填参数 service_name 或 error_log")

        event = NormalizedErrorEvent(
            service_name=str(service_name),
            error_log=str(error_log),
            query_key=str(query_key),
        )
        try:
            bundle = await self._enricher.enrich(event)
            records = [
                {"timestamp": str(r.timestamp), "level": r.level, "message": r.message[:500]}
                for r in bundle.records[:80]
            ]
            return ToolResult.text(
                json.dumps(
                    {"query_key": bundle.query_key, "record_count": len(bundle.records), "records": records},
                    ensure_ascii=False,
                )
            )
        except Exception as e:
            return ToolResult.error(f"correlation.get_info 执行失败: {str(e)}")
