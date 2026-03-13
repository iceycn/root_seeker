"""高级分析类 MCP 工具：analysis.run_full、analysis.synthesize。"""

from __future__ import annotations

import json
from typing import Any, Dict

from root_seeker.domain import NormalizedErrorEvent
from root_seeker.mcp.protocol import ToolResult, ToolSchema
from root_seeker.mcp.tools.base import BaseTool


def _report_to_json(report) -> str:
    out = {
        "analysis_id": report.analysis_id,
        "service_name": report.service_name,
        "summary": report.summary,
        "hypotheses": report.hypotheses,
        "suggestions": report.suggestions,
        "business_impact": report.business_impact,
        "related_services": [rs.service_name for rs in report.related_services],
    }
    if getattr(report, "need_more_evidence", None):
        out["NEED_MORE_EVIDENCE"] = report.need_more_evidence
    return json.dumps(out, ensure_ascii=False)


class AnalysisRunFullTool(BaseTool):
    """analysis.run_full：执行完整分析（enrich→zoekt→vector→evidence→LLM），不做勘探时使用。"""

    def __init__(self, analyzer):
        self._analyzer = analyzer

    @property
    def name(self) -> str:
        return "analysis.run_full"

    @property
    def schema(self) -> ToolSchema:
        return ToolSchema(
            name=self.name,
            description="对 error_event 执行完整分析（日志补全、Zoekt 搜索、向量检索、LLM 根因分析）。不做上游勘探时使用；若已用 code.search/code.read 收集证据，请用 analysis.synthesize 避免重复。",
            inputSchema={
                "type": "object",
                "properties": {
                    "analysis_id": {"type": "string", "description": "可选，分析 ID"},
                    "error_event": {
                        "type": "object",
                        "description": "NormalizedErrorEvent：service_name, error_log, query_key",
                        "properties": {
                            "service_name": {"type": "string"},
                            "error_log": {"type": "string"},
                            "query_key": {"type": "string"},
                        },
                        "required": ["service_name", "error_log"],
                    },
                    "use_multi_turn": {
                        "type": "boolean",
                        "description": "是否启用多轮对话。复杂根因用 true，简单用 false。",
                    },
                },
                "required": ["error_event"],
            },
        )

    async def run(self, args: Dict[str, Any], context: Dict[str, Any] | None = None) -> ToolResult:
        ev = args.get("error_event")
        if not ev or not isinstance(ev, dict):
            return ToolResult.error("缺少必填参数 error_event（需含 service_name, error_log）")
        service_name = ev.get("service_name")
        error_log = ev.get("error_log")
        query_key = ev.get("query_key") or "default_error_context"
        if not service_name or not error_log:
            return ToolResult.error("error_event 需包含 service_name 和 error_log")
        event = NormalizedErrorEvent(service_name=str(service_name), error_log=str(error_log), query_key=str(query_key))
        try:
            report = await self._analyzer.analyze(
                event,
                analysis_id=args.get("analysis_id"),
                skip_ai_driven=True,
                use_multi_turn_override=args.get("use_multi_turn"),
            )
            return ToolResult.text(_report_to_json(report))
        except Exception as e:
            return ToolResult.error(f"analysis.run_full 执行失败: {str(e)}")


class AnalysisSynthesizeTool(BaseTool):
    """analysis.synthesize：仅做 LLM 分析，接收上游工具已收集的证据，不做 enrich/zoekt/vector。"""

    def __init__(self, analyzer):
        self._analyzer = analyzer

    @property
    def name(self) -> str:
        return "analysis.synthesize"

    @property
    def schema(self) -> ToolSchema:
        return ToolSchema(
            name=self.name,
            description="基于上游工具（code.search、code.read、correlation.get_info 等）已收集的证据，仅做 LLM 根因分析。由 Orchestrator 注入 pre_collected_evidence，避免与 run_full 重复执行 enrich/zoekt/vector。",
            inputSchema={
                "type": "object",
                "properties": {
                    "analysis_id": {"type": "string", "description": "可选"},
                    "error_event": {
                        "type": "object",
                        "properties": {"service_name": {"type": "string"}, "error_log": {"type": "string"}, "query_key": {"type": "string"}},
                        "required": ["service_name", "error_log"],
                    },
                    "pre_collected_evidence": {
                        "type": "string",
                        "description": "上游工具执行结果（由 Orchestrator 注入，Plan 无需填写）",
                    },
                    "use_multi_turn": {"type": "boolean", "description": "是否多轮对话"},
                },
                "required": ["error_event"],
            },
        )

    async def run(self, args: Dict[str, Any], context: Dict[str, Any] | None = None) -> ToolResult:
        ev = args.get("error_event")
        if not ev or not isinstance(ev, dict):
            return ToolResult.error("缺少必填参数 error_event")
        service_name = ev.get("service_name")
        error_log = ev.get("error_log")
        query_key = ev.get("query_key") or "default_error_context"
        if not service_name or not error_log:
            return ToolResult.error("error_event 需包含 service_name 和 error_log")
        pre_collected = args.get("pre_collected_evidence") or ""
        event = NormalizedErrorEvent(service_name=str(service_name), error_log=str(error_log), query_key=str(query_key))
        try:
            report = await self._analyzer.synthesize_from_evidence(
                event,
                analysis_id=args.get("analysis_id"),
                pre_collected_evidence=pre_collected,
                use_multi_turn=args.get("use_multi_turn"),
            )
            return ToolResult.text(_report_to_json(report))
        except Exception as e:
            return ToolResult.error(f"analysis.synthesize 执行失败: {str(e)}")


# 向后兼容：analysis.run 作为 analysis.run_full 的别名
class AnalysisRunTool(AnalysisRunFullTool):
    """analysis.run：向后兼容，等同于 analysis.run_full。"""

    @property
    def name(self) -> str:
        return "analysis.run"
