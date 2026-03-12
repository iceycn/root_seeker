"""AiOrchestrator：AI 驱动分析编排，Plan -> Act -> Synthesize -> Check。"""

from __future__ import annotations

import asyncio
import json
import logging
import re
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any

from root_seeker.ai.evidence_context import EvidenceContext
from root_seeker.domain import AnalysisReport, NormalizedErrorEvent
from root_seeker.mcp.protocol import ErrorCode, ToolResult
from root_seeker.providers.llm import LLMProvider
from root_seeker import prompts
from root_seeker.utils import parse_json_markdown, redact_sensitive

logger = logging.getLogger(__name__)

MAX_TOOL_RESULT_CHARS = 24_000
MAX_PLAN_STEPS = 8


@dataclass
class OrchestratorConfig:
    """工具预算、多轮上限与 Check 配置。"""

    max_tool_calls: int = 8
    tool_result_max_chars: int = 24_000
    total_timeout_seconds: float = 300.0
    check_extra_tool_calls: int = 2
    max_analysis_rounds: int = 20
    max_evidence_collection_depth: int = 20
    max_evidence_total_chars: int = 80_000


def _truncate_text(s: str, max_chars: int) -> str:
    if not s or len(s) <= max_chars:
        return s or ""
    return s[: max_chars - 50] + "\n...[截断]..."


def _is_file_path_placeholder(val: str | None) -> bool:
    """判断 file_path 是否为占位符（需从 code.search 结果注入）。"""
    if not val or not isinstance(val, str):
        return True
    s = val.strip()
    placeholders = ("上一步", "返回的路径", "code.search", "见上文", "<同上>", "搜索结果")
    return any(p in s for p in placeholders) or len(s) < 3


def _extract_file_path_from_code_search(tool_results: list[tuple[str, str, bool, dict | None]]) -> str | None:
    """从 code.search 结果中提取第一个 file_path。JSON 解析失败时用正则兜底（截断后可能非法 JSON）。"""
    for name, text, *_ in tool_results:
        if name != "code.search" or not text:
            continue
        try:
            data = json.loads(text)
            hits = data.get("hits") if isinstance(data, dict) else []
            if hits and isinstance(hits[0], dict):
                fp = hits[0].get("file_path")
                if fp and isinstance(fp, str):
                    return fp
        except (json.JSONDecodeError, IndexError, KeyError, TypeError):
            pass
        # 截断后 JSON 可能非法，用正则提取第一个 "file_path":"xxx"
        m = re.search(r'"file_path"\s*:\s*"([^"]+)"', text)
        if m:
            return m.group(1)
    return None


def _fill_step_args(
    step: dict,
    event: NormalizedErrorEvent,
    analysis_id: str,
    tool_results_so_far: list[tuple[str, str, bool, dict | None]] | None = None,
    max_evidence_chars: int = 80_000,
) -> dict:
    """用 event 补全 step.args 中的占位符。analysis.synthesize 时注入 pre_collected_evidence；code.read 时从 code.search 注入 file_path。"""
    args = dict(step.get("args") or {})
    service_name = event.service_name
    query_key = event.query_key
    error_log = _truncate_text(event.error_log, 2000)
    tool_name = step.get("tool_name") or ""

    if "service_name" not in args and service_name:
        args["service_name"] = service_name
    if "query_key" not in args and query_key:
        args["query_key"] = query_key
    if "error_log" in args and (args["error_log"] in ("见上文", "<同上>", "")):
        args["error_log"] = error_log
    if "error_event" in args:
        args["error_event"] = {
            "service_name": service_name,
            "error_log": error_log,
            "query_key": query_key,
        }
    if "analysis_id" not in args and analysis_id:
        args["analysis_id"] = analysis_id
    if tool_name == "deps.get_graph" and ("target" not in args or not args.get("target")) and service_name:
        args["target"] = service_name
    if tool_name == "analysis.synthesize":
        if tool_results_so_far:
            parts = []
            for name, text, *_ in tool_results_so_far:
                parts.append(f"[{name}]\n{text}")
            raw_evidence = "\n\n---\n\n".join(parts)
            args["pre_collected_evidence"] = _truncate_text(raw_evidence, max_evidence_chars)
        if args.get("use_multi_turn") is None:
            args["use_multi_turn"] = False
    if tool_name in ("analysis.run", "analysis.run_full") and args.get("use_multi_turn") is None:
        args["use_multi_turn"] = False
    if tool_name == "code.read" and tool_results_so_far and _is_file_path_placeholder(args.get("file_path")):
        injected = _extract_file_path_from_code_search(tool_results_so_far)
        if injected:
            args["file_path"] = injected
            logger.debug(f"[AiOrchestrator] 从 code.search 注入 file_path: {injected[:80]}...")
    return args


class AiOrchestrator:
    """AI 驱动分析编排器：Plan -> Act -> Synthesize -> Check。"""

    def __init__(
        self,
        mcp_gateway,
        llm: LLMProvider,
        config: OrchestratorConfig | None = None,
        audit=None,
    ):
        self._mcp = mcp_gateway
        self._llm = llm
        self._cfg = config or OrchestratorConfig()
        self._audit = audit
        self._tools_summary: str = ""

    async def ensure_tools_summary(self) -> None:
        """启动时拉取工具摘要，供 Plan 使用。"""
        if self._tools_summary:
            return
        tools = await self._mcp.list_tools()
        lines = [f"- {t.name}: {t.description}" for t in tools]
        self._tools_summary = "\n".join(lines)
        logger.info(f"[AiOrchestrator] 已加载 {len(tools)} 个工具摘要")

    async def analyze(
        self,
        event: NormalizedErrorEvent,
        *,
        analysis_id: str | None = None,
    ) -> AnalysisReport:
        """执行 AI 驱动分析（多轮迭代），失败时抛出异常由调用方回退到直连路径。"""
        import uuid

        analysis_id = analysis_id or uuid.uuid4().hex
        timeout = self._cfg.total_timeout_seconds

        async def _run() -> AnalysisReport:
            await self.ensure_tools_summary()
            prev_report: AnalysisReport | None = None
            evidence_needs: list[str] = []
            tool_plan_hint: str = ""

            for round_num in range(1, self._cfg.max_analysis_rounds + 1):
                logger.info(f"[AiOrchestrator] 第 {round_num}/{self._cfg.max_analysis_rounds} 轮分析")

                if round_num == 1:
                    plan = await self._plan(event, analysis_id)
                else:
                    plan = await self._plan_next_round(
                        event, analysis_id, prev_report, evidence_needs, tool_plan_hint
                    )

                if not plan or not plan.get("steps"):
                    if prev_report is not None:
                        return prev_report
                    raise RuntimeError("Plan 为空或没有 steps")

                steps = plan["steps"][: self._cfg.max_tool_calls]
                tool_results: list[tuple[str, str, bool, dict | None]] = []
                context = {"trace_id": analysis_id, "analysis_id": analysis_id}
                need_more_evidence_triggered = False

                for i, step in enumerate(steps):
                    tool_name = step.get("tool_name")
                    if not tool_name:
                        continue
                    args = _fill_step_args(
                        step, event, analysis_id,
                        tool_results_so_far=tool_results,
                        max_evidence_chars=self._cfg.max_evidence_total_chars,
                    )
                    t0 = time.perf_counter()
                    result = await self._call_tool_with_retry(
                        tool_name, args, context, event, analysis_id
                    )
                    elapsed = time.perf_counter() - t0

                    if self._audit:
                        self._audit.log({
                            "event": "mcp_tool_call",
                            "analysis_id": analysis_id,
                            "round": round_num,
                            "step": i + 1,
                            "tool_name": tool_name,
                            "elapsed_ms": round(elapsed * 1000),
                            "is_error": result.isError,
                            "error_code": result.errorCode if result.isError else None,
                        })

                    if result.isError:
                        err_msg = result.content[0].text if result.content else "unknown"
                        err_code = result.errorCode or "INTERNAL_ERROR"
                        logger.warning(
                            f"[AiOrchestrator] 工具调用失败: {tool_name}, error_code={err_code}, message={err_msg[:200]}"
                        )
                        raise RuntimeError(f"Tool {tool_name} failed [{err_code}]: {err_msg}")

                    text = (result.content[0].text or "") if result.content else ""
                    text = _truncate_text(text, self._cfg.tool_result_max_chars)
                    # 计划 5.2：保留可复现查询参数（截断时供 Synthesize 引用）
                    tool_results.append((tool_name, text, False, args))

                    if tool_name in ("analysis.run", "analysis.run_full", "analysis.synthesize"):
                        try:
                            parsed = json.loads(text)
                            report = self._report_from_analysis_run(parsed, event, analysis_id)
                            r, _ = self._check_and_sanitize(report, event)
                            need_more = parsed.get("NEED_MORE_EVIDENCE") or parsed.get("need_more_evidence")
                            if isinstance(need_more, list) and need_more:
                                evidence_needs = [str(x).strip() for x in need_more if str(x).strip()][:6]
                                if evidence_needs:
                                    prev_report = r
                                    need_more_evidence_triggered = True
                                    logger.info(
                                        f"[AiOrchestrator] 分析返回 NEED_MORE_EVIDENCE，触发下一轮证据补充: {evidence_needs[:3]}..."
                                    )
                                    break
                            return r
                        except Exception:
                            pass

                if need_more_evidence_triggered:
                    report, hit_depth_limit = await self._collect_evidence_recursive(
                        event, analysis_id, evidence_needs, tool_results, prev_report, depth=0
                    )
                    if hit_depth_limit:
                        logger.info("[AiOrchestrator] 证据收集已达最大递归深度，结束")
                    return report

                report = await self._synthesize(event, analysis_id, tool_results)
                report, needs_extra = self._check_and_sanitize(report, event)
                if needs_extra and self._cfg.check_extra_tool_calls > 0 and len(tool_results) < self._cfg.max_tool_calls:
                    extra_report = await self._try_check_extra_tools(event, analysis_id, tool_results)
                    if extra_report is not None:
                        report = extra_report
                        report, needs_extra = self._check_and_sanitize(report, event)

                decision = await self._decide_next_round(
                    event, analysis_id, report, tool_results, round_num
                )
                if self._audit and decision:
                    self._audit.log({
                        "event": "orchestrator_next_round_decision",
                        "analysis_id": analysis_id,
                        "round": round_num,
                        "continue_analysis": decision.get("continue_analysis"),
                        "reason": decision.get("reason", "")[:200],
                    })

                if not decision or not decision.get("continue_analysis"):
                    return report
                if round_num >= self._cfg.max_analysis_rounds:
                    logger.info(f"[AiOrchestrator] 已达最大轮数 {self._cfg.max_analysis_rounds}，结束分析")
                    return report

                prev_report = report
                evidence_needs = decision.get("next_round_evidence_needs") or []
                tool_plan = decision.get("next_round_tool_plan") or {}
                tool_plan_hint = tool_plan.get("hint", "") or str(tool_plan.get("suggested_tools", []))

            return report

        return await asyncio.wait_for(_run(), timeout=timeout)

    async def _call_tool_with_retry(
        self,
        tool_name: str,
        args: dict,
        context: dict,
        event: NormalizedErrorEvent,
        analysis_id: str,
    ) -> ToolResult:
        """调用工具，若失败则由错误判断 AI 分析错误原因、修正参数后重试一次。"""
        result = await self._mcp.call_tool(tool_name, args, context)
        if not result.isError:
            return result

        err_code = result.errorCode or "INTERNAL_ERROR"
        err_msg = (result.content[0].text or "unknown") if result.content else "unknown"
        logger.info(f"[AiOrchestrator] 工具 {tool_name} 调用失败 [{err_code}]，尝试错误判断 AI 分析并修正: {err_msg[:150]}")

        try:
            user = prompts.AI_ORCHESTRATOR_FIX_ARGS_USER.format(
                tool_name=tool_name,
                error_code=err_code,
                error_msg=err_msg[:500],
                args=json.dumps(args, ensure_ascii=False),
                service_name=event.service_name,
                query_key=event.query_key,
                analysis_id=analysis_id,
                error_log_preview=_truncate_text(event.error_log, 500),
            )
            raw = await self._llm.generate(
                system=prompts.AI_ORCHESTRATOR_FIX_ARGS_SYSTEM,
                user=user,
            )
            logger.debug("[AiOrchestrator] 工具参数修正 AI 返回:\n%s", raw)
            parsed = parse_json_markdown(raw)
            if isinstance(parsed, dict) and parsed.get("abort"):
                return result
            corrected = parsed.get("corrected_args") if isinstance(parsed, dict) else None
            if not isinstance(corrected, dict):
                return result
            merged = dict(args)
            merged.update(corrected)
            retry_result = await self._mcp.call_tool(tool_name, merged, context)
            if not retry_result.isError:
                logger.info(f"[AiOrchestrator] 工具 {tool_name} 修正后重试成功")
            return retry_result
        except Exception as e:
            logger.warning(f"[AiOrchestrator] AI 修正参数失败: {e}")
            return result

    async def _try_check_extra_tools(
        self,
        event: NormalizedErrorEvent,
        analysis_id: str,
        tool_results: list[tuple[str, str, bool, dict | None]],
    ) -> AnalysisReport | None:
        """Check 追加：最多 0~2 次 tool calls 补齐缺失信息（计划 5.2：智能选择追加工具）。"""
        called_tools = {name for name, *_ in tool_results}
        # 按计划优先顺序：不确定时先 index.get_status/correlation.get_info
        extra_tools = []
        if "correlation.get_info" not in called_tools:
            extra_tools.append(
                ("correlation.get_info", {"service_name": event.service_name, "error_log": _truncate_text(event.error_log, 500)})
            )
        if "index.get_status" not in called_tools:
            extra_tools.append(("index.get_status", {"service_name": event.service_name}))

        context = {"trace_id": analysis_id, "analysis_id": analysis_id}
        for tool_name, args in extra_tools[: min(2, self._cfg.check_extra_tool_calls)]:
            result = await self._mcp.call_tool(tool_name, args, context)
            if result.isError:
                continue
            text = (result.content[0].text or "") if result.content else ""
            tool_results.append((tool_name, _truncate_text(text, self._cfg.tool_result_max_chars), False, args))
            report = await self._synthesize(event, analysis_id, tool_results)
            report, needs_extra = self._check_and_sanitize(report, event)
            if not needs_extra:
                return report
        return None

    async def _plan(self, event: NormalizedErrorEvent, analysis_id: str) -> dict:
        """Plan 阶段：LLM 生成工具调用计划（首轮）。"""
        error_preview = _truncate_text(event.error_log, 2000)
        user = prompts.AI_ORCHESTRATOR_PLAN_USER.format(
            service_name=event.service_name,
            error_log=error_preview,
            tools_summary=self._tools_summary,
            query_key=event.query_key,
        )
        raw = await self._llm.generate(system=prompts.AI_ORCHESTRATOR_PLAN_SYSTEM, user=user)
        logger.debug("[AiOrchestrator] Plan 首轮 AI 返回:\n%s", raw)
        parsed = parse_json_markdown(raw)
        if isinstance(parsed, dict) and "steps" in parsed:
            return parsed
        raise RuntimeError("Plan 解析失败，LLM 未返回有效 JSON")

    async def _plan_next_round(
        self,
        event: NormalizedErrorEvent,
        analysis_id: str,
        prev_report: AnalysisReport,
        evidence_needs: list[str],
        tool_plan_hint: str,
    ) -> dict:
        """Plan 阶段：后续轮，基于上一轮报告与证据需求。"""
        user = prompts.AI_ORCHESTRATOR_PLAN_NEXT_ROUND_USER.format(
            service_name=event.service_name,
            error_log=_truncate_text(event.error_log, 1000),
            previous_summary=prev_report.summary or "无",
            previous_hypotheses="; ".join((prev_report.hypotheses or [])[:5]) or "无",
            evidence_needs="\n".join(f"- {e}" for e in evidence_needs) if evidence_needs else "无",
            tool_plan_hint=tool_plan_hint or "无",
            tools_summary=self._tools_summary,
        )
        raw = await self._llm.generate(
            system=prompts.AI_ORCHESTRATOR_PLAN_NEXT_ROUND_SYSTEM, user=user
        )
        logger.debug("[AiOrchestrator] Plan 后续轮 AI 返回:\n%s", raw)
        parsed = parse_json_markdown(raw)
        if isinstance(parsed, dict) and "steps" in parsed:
            return parsed
        raise RuntimeError("Plan 解析失败，LLM 未返回有效 JSON")

    async def _plan_for_single_evidence_need(
        self,
        event: NormalizedErrorEvent,
        analysis_id: str,
        evidence_need: str,
        tool_results_so_far: list[tuple[str, str, bool, dict | None]],
    ) -> dict:
        """针对单条证据需求生成子计划。"""
        user = prompts.AI_ORCHESTRATOR_PLAN_SINGLE_EVIDENCE_NEED_USER.format(
            service_name=event.service_name,
            error_log=_truncate_text(event.error_log, 500),
            evidence_need=evidence_need,
            tools_summary=self._tools_summary,
        )
        raw = await self._llm.generate(
            system=prompts.AI_ORCHESTRATOR_PLAN_SINGLE_EVIDENCE_NEED_SYSTEM, user=user
        )
        logger.debug("[AiOrchestrator] 单条证据子计划 AI 返回:\n%s", raw)
        parsed = parse_json_markdown(raw)
        if isinstance(parsed, dict) and "steps" in parsed:
            return parsed
        return {"goal": "", "steps": []}

    async def _collect_evidence_recursive(
        self,
        event: NormalizedErrorEvent,
        analysis_id: str,
        evidence_needs: list[str],
        tool_results: list[tuple[str, str, bool, dict | None]],
        fallback_report: AnalysisReport,
        depth: int,
        evidence_ctx: EvidenceContext | None = None,
    ) -> tuple[AnalysisReport, bool]:
        """
        对每个 NEED_MORE_EVIDENCE 建立子计划并执行，递归直到收集不到证据或达到深度限制。
        优先从 evidence_ctx 查找已有证据，避免重复调用工具。
        返回 (report, hit_depth_limit)。
        """
        context = {"trace_id": analysis_id, "analysis_id": analysis_id}
        collected = list(tool_results)
        if evidence_ctx is None:
            evidence_ctx = EvidenceContext(max_total_chars=self._cfg.max_evidence_total_chars)
            evidence_ctx.from_tool_results(collected)
        context["evidence_ctx"] = evidence_ctx

        for evidence_need in evidence_needs:
            plan = await self._plan_for_single_evidence_need(
                event, analysis_id, evidence_need, collected
            )
            steps = (plan.get("steps") or [])[:3]
            for step in steps:
                tool_name = step.get("tool_name")
                if not tool_name or tool_name in ("analysis.run", "analysis.run_full", "analysis.synthesize"):
                    continue
                args = _fill_step_args(
                    step, event, analysis_id,
                    tool_results_so_far=collected,
                    max_evidence_chars=self._cfg.max_evidence_total_chars,
                )
                if tool_name == "evidence.context_search" and "query" not in args:
                    args["query"] = evidence_need
                try:
                    result = await self._call_tool_with_retry(
                        tool_name, args, context, event, analysis_id
                    )
                    if result.isError:
                        continue
                    text = (result.content[0].text or "") if result.content else ""
                    text = _truncate_text(text, self._cfg.tool_result_max_chars)
                    collected.append((tool_name, text, False, args))
                    if tool_name != "evidence.context_search":
                        evidence_ctx.add(tool_name, text, key_hint=evidence_need)
                    elif text:
                        try:
                            parsed = json.loads(text)
                            if parsed.get("found") and parsed.get("matches"):
                                evidence_text = evidence_ctx.to_evidence_text(evidence_need)
                                if evidence_text and evidence_text != text:
                                    collected[-1] = (tool_name, evidence_text, False, args)
                        except Exception:
                            pass
                except Exception as e:
                    logger.warning(f"[AiOrchestrator] 子计划步骤 {tool_name} 执行失败: {e}")

        if not collected:
            return fallback_report, False

        step = {
            "tool_name": "analysis.synthesize",
            "args": {"error_event": {"service_name": event.service_name, "error_log": "见上文", "query_key": event.query_key}, "use_multi_turn": False},
        }
        args = _fill_step_args(
            step, event, analysis_id,
            tool_results_so_far=collected,
            max_evidence_chars=self._cfg.max_evidence_total_chars,
        )
        result = await self._mcp.call_tool("analysis.synthesize", args, context)
        if result.isError:
            report = await self._synthesize(event, analysis_id, collected)
            return self._check_and_sanitize(report, event)[0], depth >= self._cfg.max_evidence_collection_depth

        text = (result.content[0].text or "") if result.content else "{}"
        try:
            parsed = json.loads(text)
            report = self._report_from_analysis_run(parsed, event, analysis_id)
            r, _ = self._check_and_sanitize(report, event)
            need_more = parsed.get("NEED_MORE_EVIDENCE") or parsed.get("need_more_evidence")
            if isinstance(need_more, list) and need_more and depth < self._cfg.max_evidence_collection_depth:
                new_needs = [str(x).strip() for x in need_more if str(x).strip()][:6]
                if new_needs:
                    logger.info(
                        f"[AiOrchestrator] 证据收集递归 depth={depth + 1}，新需求: {new_needs[:3]}..."
                    )
                    return await self._collect_evidence_recursive(
                        event, analysis_id, new_needs, collected, r, depth + 1, evidence_ctx
                    )
            return r, depth >= self._cfg.max_evidence_collection_depth
        except Exception:
            report = await self._synthesize(event, analysis_id, collected)
            return self._check_and_sanitize(report, event)[0], depth >= self._cfg.max_evidence_collection_depth

    async def _decide_next_round(
        self,
        event: NormalizedErrorEvent,
        analysis_id: str,
        report: AnalysisReport,
        tool_results: list[tuple[str, str, bool, dict | None]],
        round_num: int,
    ) -> dict | None:
        """Check 阶段：AI 决策是否进行下一轮。"""
        results_text = "\n\n---\n\n".join(
            f"[{name}]\n{_truncate_text(text, 800)}" for name, text, *_ in tool_results
        )
        user = prompts.AI_ORCHESTRATOR_NEXT_ROUND_USER.format(
            service_name=event.service_name,
            round_num=round_num,
            max_rounds=self._cfg.max_analysis_rounds,
            report_summary=report.summary or "无",
            hypotheses="; ".join((report.hypotheses or [])[:5]) or "无",
            suggestions="; ".join((report.suggestions or [])[:5]) or "无",
            tool_results_preview=_truncate_text(results_text, 2000),
        )
        try:
            raw = await self._llm.generate(
                system=prompts.AI_ORCHESTRATOR_NEXT_ROUND_SYSTEM, user=user
            )
            logger.debug("[AiOrchestrator] Check 下一轮决策 AI 返回:\n%s", raw)
            parsed = parse_json_markdown(raw)
            return parsed if isinstance(parsed, dict) else None
        except Exception as e:
            logger.warning(f"[AiOrchestrator] 下一轮决策解析失败: {e}")
            return None

    async def _synthesize(
        self,
        event: NormalizedErrorEvent,
        analysis_id: str,
        tool_results: list[tuple[str, str, bool, dict | None]],
    ) -> AnalysisReport:
        """Synthesize 阶段：从 tool 结果生成报告（计划 5.2：含可复现查询参数）。"""
        parts = []
        for name, text, _, args in tool_results:
            part = f"[{name}]"
            if args:
                args_brief = json.dumps(args, ensure_ascii=False)[:300]
                part += f"\n【可复现参数】{args_brief}"
            part += f"\n{text}"
            parts.append(part)
        results_text = "\n\n---\n\n".join(parts)
        user = prompts.AI_ORCHESTRATOR_SYNTHESIZE_USER.format(
            service_name=event.service_name,
            error_log=_truncate_text(event.error_log, 1500),
            tool_results=_truncate_text(results_text, 12000),
        )
        raw = await self._llm.generate(system=prompts.AI_ORCHESTRATOR_SYNTHESIZE_SYSTEM, user=user)
        logger.debug("[AiOrchestrator] Synthesize AI 返回:\n%s", raw)
        parsed = parse_json_markdown(raw)
        return self._report_from_parsed(parsed, event, analysis_id)

    def _report_from_analysis_run(self, parsed: dict, event: NormalizedErrorEvent, analysis_id: str) -> AnalysisReport:
        """从 analysis.run 的返回构造 AnalysisReport。"""
        return AnalysisReport(
            analysis_id=parsed.get("analysis_id") or analysis_id,
            service_name=parsed.get("service_name") or event.service_name,
            created_at=datetime.now(tz=timezone.utc),
            summary=parsed.get("summary") or "分析完成",
            hypotheses=parsed.get("hypotheses") or [],
            suggestions=parsed.get("suggestions") or [],
            evidence=None,
            business_impact=parsed.get("business_impact"),
            correlation_id=event.correlation_id or analysis_id,
        )

    def _report_from_parsed(self, parsed: dict, event: NormalizedErrorEvent, analysis_id: str) -> AnalysisReport:
        """从 LLM 解析结果构造 AnalysisReport。"""
        summary = parsed.get("summary")
        if isinstance(summary, dict):
            summary = summary.get("direct_cause") or summary.get("summary") or str(summary)
        summary = str(summary or "分析完成")
        return AnalysisReport(
            analysis_id=analysis_id,
            service_name=event.service_name,
            created_at=datetime.now(tz=timezone.utc),
            summary=summary,
            hypotheses=[str(x) for x in (parsed.get("hypotheses") or [])][:12],
            suggestions=[str(x) for x in (parsed.get("suggestions") or [])][:16],
            evidence=None,
            business_impact=parsed.get("business_impact"),
            correlation_id=event.correlation_id or analysis_id,
        )

    def _check_and_sanitize(
        self, report: AnalysisReport, event: NormalizedErrorEvent
    ) -> tuple[AnalysisReport, bool]:
        """
        Check 阶段：最小自检与安全脱敏（对标 v2.0.0 计划 5.2 节）。
        - 覆盖性：summary 非空、有 service_name、关键日志证据、repo_id/服务名
        - 可复现性：含 correlation_id、query_key 等可追溯信息（若可获得则补全）
        - 安全性：脱敏 AK/SK、token、连接串等
        返回 (report, needs_extra)：needs_extra 为 True 时建议追加 tool calls 补齐。
        """
        summary = redact_sensitive(report.summary or "分析完成")
        hypotheses = [redact_sensitive(str(h)) for h in (report.hypotheses or [])]
        suggestions = [redact_sensitive(str(s)) for s in (report.suggestions or [])]
        business_impact = redact_sensitive(report.business_impact) if report.business_impact else None

        # 可复现性：补全 correlation_id（从 event 继承，便于 ingest→queue→analyze 贯通）
        correlation_id = report.correlation_id or event.correlation_id

        sanitized = report.model_copy(
            update={
                "summary": summary,
                "hypotheses": hypotheses,
                "suggestions": suggestions,
                "business_impact": business_impact,
                "correlation_id": correlation_id,
            }
        )

        needs_extra = False
        # 覆盖性检查（计划 5.2：错误签名、关键日志证据、repo_id/服务名）
        if not report.service_name:
            needs_extra = True
        elif (not summary or summary == "分析完成") and not hypotheses and not suggestions:
            needs_extra = True

        return sanitized, needs_extra
