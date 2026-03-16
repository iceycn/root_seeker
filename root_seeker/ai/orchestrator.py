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

from root_seeker.ai.context_discovery import (
    build_hints_for_plan,
    discover_refs_from_error_log,
    extract_relevance_keywords,
    DiscoveredContext,
)
from root_seeker.ai.evidence_context import EvidenceContext
from root_seeker.ai.prompt_builder import (
    AIPromptContext,
    build_focus_chain,
    build_fix_args_user_prompt,
    build_next_round_decision_user_prompt,
    build_plan_next_round_user_prompt,
    build_plan_user_prompt,
    build_synthesize_user_prompt,
)
from root_seeker.ai.rule_context import build_rule_context_hint, extract_paths_from_tool_results
from root_seeker.hooks.hub import HookHub
from root_seeker.mcp.format_response import (
    UNRECOVERABLE_ERROR_CODES,
    extract_missing_param_from_error,
    format_tool_error,
)
from root_seeker.domain import AnalysisReport, NormalizedErrorEvent
from root_seeker.mcp.protocol import ErrorCode, ToolResult, ToolSchema
from root_seeker.providers.llm import LLMProvider
from root_seeker import prompts
from root_seeker.utils import parse_json_markdown, redact_sensitive

logger = logging.getLogger(__name__)

MAX_TOOL_RESULT_CHARS = 24_000
MAX_PLAN_STEPS = 8

# Plan 阶段限制的工具（root_seeker 暂无写操作工具，预留）
PLAN_RESTRICTED_TOOLS: set[str] = set()

# 全量分析工具仅作兜底，不得作为首步（勘探优先）
_ANALYSIS_RUN_TOOLS: set[str] = {"analysis.run", "analysis.run_full"}

# tool_use_loop 模式排除的工具（模型直接输出 JSON 报告，不调用 synthesis）
_TOOL_USE_LOOP_EXCLUDED_TOOLS: set[str] = {"analysis.synthesize", "analysis.run", "analysis.run_full"}


def _mcp_tool_schema_to_openai_function(schema: ToolSchema) -> dict[str, Any]:
    """将 MCP ToolSchema 转为 OpenAI function 格式。"""
    inp = schema.inputSchema or {}
    return {
        "type": "function",
        "function": {
            "name": schema.name,
            "description": schema.description or "",
            "parameters": {
                "type": inp.get("type", "object"),
                "properties": inp.get("properties") or {},
                "required": inp.get("required") or [],
            },
        },
    }


def _reorder_steps_cline_mode(steps: list[dict]) -> list[dict]:
    """若 analysis.run/analysis.run_full 出现在前两步，移至末尾，保证勘探优先。"""
    if len(steps) < 2:
        return steps
    early_analysis = [s for i, s in enumerate(steps[:2]) if s.get("tool_name") in _ANALYSIS_RUN_TOOLS]
    rest = [s for s in steps if s.get("tool_name") not in _ANALYSIS_RUN_TOOLS]
    if not early_analysis:
        return steps
    # 将 early analysis 移到末尾
    reordered = rest + early_analysis
    if reordered != steps:
        logger.info(
            "[AiOrchestrator] 勘探优先：将 %s 从首步移至末尾",
            [s.get("tool_name") for s in early_analysis],
        )
    return reordered


@dataclass
class OrchestratorConfig:
    """工具预算、多轮上限与 Check 配置。"""

    orchestration_mode: str = "plan_act"  # plan_act | tool_use_loop（Cline/Cursor 风格：模型每次决定是否继续 tool call）
    max_tool_calls: int = 8
    tool_result_max_chars: int = 24_000
    total_timeout_seconds: float = 300.0
    check_extra_tool_calls: int = 2
    max_analysis_rounds: int = 20
    max_evidence_collection_depth: int = 20
    max_evidence_total_chars: int = 80_000
    max_evidence_total_tokens: int | None = None  # token 预算，None 时用 chars/2 近似
    llm_multi_turn_enabled: bool = True  # 与直连路径一致：analysis.synthesize 使用多轮 LLM
    mistake_limit: int = 3  # 同一工具连续失败 N 次后中止
    mcp_ready_timeout_seconds: float = 10.0  # 等待 MCP 连接就绪超时（pWaitFor）
    llm_retry_max_attempts: int = 3  # LLM 调用失败时自动重试次数（指数退避 2s×2^attempt）
    checkpoint_enabled: bool = False  # 轻量 checkpoint 保存状态（供 audit/debug）
    # 长对话时压缩上下文
    compact_context_after_rounds: int = 5  # 超过此轮数后触发压缩
    compact_context_threshold_chars: int = 40_000  # 或累计 tool_results 超过此字符数时压缩
    compact_context_threshold_tokens: int | None = None  # token 预算触发压缩，None 时用 chars/2
    compact_context_keep_last_n: int = 6  # 压缩时保留最近 N 个工具结果


def _truncate_text(s: str, max_chars: int, repro_hint: str | None = None) -> str:
    """单次截断：截断时附带原长说明；可选保留可复现参数。v3.0.0：附加 is_truncated/original_length 供 LLM 感知。"""
    if not s or len(s) <= max_chars:
        return s or ""
    suffix = f"\n...[截断，原长 {len(s)} 字]..."
    if repro_hint:
        suffix += f"\n【可复现参数】{repro_hint}"
    meta = f"\n[truncation_meta: is_truncated=true, original_length={len(s)}]"
    return s[: max_chars - len(suffix) - len(meta)] + suffix + meta


def _truncate_tool_result_struct(text: str, max_chars: int, tool_name: str, repro_hint: str | None = None) -> str:
    """结构感知截断：对 JSON 类 tool_result 保留关键字段（file_path/line/hits 等），截断 preview/content 等长文本。"""
    if not text or len(text) <= max_chars:
        return text or ""
    struct_tools = (
        "code.search", "correlation.get_info", "evidence.context_search", "code.resolve_symbol",
        "code.read", "deps.parse_external", "deps.get_graph",
    )
    if tool_name not in struct_tools:
        return _truncate_text(text, max_chars, repro_hint)
    try:
        data = json.loads(text)
        if not isinstance(data, dict):
            return _truncate_text(text, max_chars, repro_hint)
        original_len = len(text)
        preview_max = 400
        if "hits" in data and isinstance(data["hits"], list):
            for h in data["hits"]:
                if isinstance(h, dict) and "preview" in h and isinstance(h["preview"], str):
                    if len(h["preview"]) > preview_max:
                        h["preview"] = h["preview"][:preview_max] + "..."
        if "matches" in data and isinstance(data["matches"], list):
            for m in data["matches"]:
                if isinstance(m, dict):
                    for key in ("preview", "content_preview"):
                        if key in m and isinstance(m[key], str) and len(m[key]) > preview_max:
                            m[key] = m[key][:preview_max] + "..."
        if "locations" in data and isinstance(data["locations"], list):
            for loc in data["locations"]:
                if isinstance(loc, dict) and "preview" in loc and isinstance(loc["preview"], str):
                    if len(loc["preview"]) > preview_max:
                        loc["preview"] = loc["preview"][:preview_max] + "..."
        if "content" in data and isinstance(data["content"], str) and len(data["content"]) > 2000:
            data["content"] = data["content"][:2000] + "\n...[截断]..."
        if "nodes" in data and isinstance(data["nodes"], list) and len(data["nodes"]) > 30:
            data["_nodes_truncated"] = len(data["nodes"]) - 30
            data["nodes"] = data["nodes"][:30]
        if "edges" in data and isinstance(data["edges"], list) and len(data["edges"]) > 50:
            data["_edges_truncated"] = len(data["edges"]) - 50
            data["edges"] = data["edges"][:50]
        out = json.dumps(data, ensure_ascii=False)
        if len(out) > max_chars:
            out = out[: max_chars - 80] + f"\n...[截断]...\n[truncation_meta: is_truncated=true, original_length={original_len}]"
        else:
            out += f"\n[truncation_meta: is_truncated=true, original_length={original_len}]"
        if repro_hint:
            out += f"\n【可复现参数】{repro_hint}"
        return out
    except (json.JSONDecodeError, TypeError):
        return _truncate_text(text, max_chars, repro_hint)


def _build_repro_hint(event: NormalizedErrorEvent, tool_name: str) -> str | None:
    """为 correlation/index 类工具构建可复现参数提示，供截断时保留。"""
    if tool_name not in ("correlation.get_info", "index.get_status"):
        return None
    parts = []
    if event.query_key:
        parts.append(f"query_key={event.query_key}")
    if event.correlation_id:
        parts.append(f"trace_id={event.correlation_id}")
    return ", ".join(parts) if parts else None


def _truncate_multilevel(text: str, max_chars: int, threshold_ratio: float = 0.9) -> str:
    """多级截断：按接近上限程度选择 half/quarter。"""
    if not text or len(text) <= max_chars:
        return text or ""
    if len(text) / max_chars >= threshold_ratio:
        # 超过 90% 时用 quarter 更激进截断
        keep_chars = max_chars // 4
    else:
        keep_chars = max_chars // 2
    suffix = f"\n...[截断，原长 {len(text)} 字，保留 {keep_chars} 字]..."
    return text[: keep_chars - len(suffix)] + suffix


def _should_compact_context(
    round_num: int,
    prev_tool_results: list[tuple[str, str, bool, dict | None]],
    compact_after_rounds: int,
    compact_threshold_chars: int,
    compact_threshold_tokens: int | None = None,
) -> bool:
    """长对话时需压缩上下文。字符或 token 超预算即触发。"""
    if round_num < compact_after_rounds:
        return False
    total_chars = sum(len(t[1]) for t in prev_tool_results)
    if total_chars > compact_threshold_chars:
        return True
    if compact_threshold_tokens is not None and compact_threshold_tokens > 0:
        from root_seeker.ai.token_budget import count_tokens
        total_tokens = sum(count_tokens(t[1]) for t in prev_tool_results)
        return total_tokens > compact_threshold_tokens
    return False


def _build_diagnosis_summary(
    tool_results: list[tuple[str, str, bool, dict | None]] | None,
) -> dict | None:
    """v3.0.0 每轮诊断摘要：degraded_modes、truncations、key_evidence_refs。"""
    if not tool_results:
        return None
    degraded: set[str] = set()
    key_refs: list[dict] = []
    truncations: list[dict] = []
    for name, text, is_err, args in tool_results:
        if is_err and text:
            try:
                parsed = json.loads(text)
                if isinstance(parsed, dict) and "degraded_modes" in parsed:
                    for m in parsed["degraded_modes"] or []:
                        degraded.add(str(m))
            except (json.JSONDecodeError, TypeError):
                pass
        if not is_err and text:
            try:
                data = json.loads(text)
                if isinstance(data, dict):
                    if "file_path" in data:
                        key_refs.append({
                            "kind": name,
                            "file_path": data.get("file_path", ""),
                            "line_range": (data.get("start_line"), data.get("end_line")),
                            "repro_hint": (args or {}).get("query") or (args or {}).get("file_path", ""),
                        })
                    if "hits" in data:
                        for h in (data["hits"] or [])[:3]:
                            fp = h.get("file_path") or h.get("location", {}).get("file_path")
                            if fp:
                                key_refs.append({
                                    "kind": name,
                                    "file_path": fp,
                                    "line_range": h.get("line_number"),
                                    "repro_hint": (args or {}).get("query", ""),
                                })
                    if "locations" in data:
                        for loc in (data["locations"] or [])[:3]:
                            fp = loc.get("file_path") or (loc.get("location") or {}).get("file_path")
                            if fp:
                                key_refs.append({
                                    "kind": name,
                                    "file_path": fp,
                                    "line_range": loc.get("line_number"),
                                    "repro_hint": (args or {}).get("symbol", ""),
                                })
                    if data.get("is_truncated"):
                        truncations.append({
                            "tool_name": name,
                            "original_length": data.get("original_length"),
                            "kept_length": data.get("kept_length") or len(text),
                        })
            except (json.JSONDecodeError, TypeError):
                pass
    if not degraded and not key_refs and not truncations:
        return None
    return {
        "degraded_modes": sorted(degraded),
        "truncations": truncations[:10],
        "key_evidence_refs": key_refs[:15],
    }


def _find_first_location_index(tool_results: list[tuple[str, str, bool, dict | None]]) -> int | None:
    """找到首次定位证据的索引（code.search/code.read 且含 file_path）。"""
    for i, (name, text, is_err, args) in enumerate(tool_results):
        if is_err or name not in ("code.search", "code.read"):
            continue
        if name == "code.read" and args and args.get("file_path"):
            return i
        if name == "code.search" and text and ("file_path" in text or "hits" in text):
            return i
    return None


def _relevance_score_tool_result(text: str, keywords: set[str]) -> int:
    """工具结果与相关性关键词的匹配数。"""
    if not keywords or not text:
        return 0
    lower = text.lower()
    return sum(1 for kw in keywords if kw and kw.lower() in lower)


def _compact_tool_results(
    tool_results: list[tuple[str, str, bool, dict | None]],
    keep_last_n: int,
    max_chars_per_result: int = 2000,
    relevance_keywords: set[str] | None = None,
) -> list[tuple[str, str, bool, dict | None]]:
    """压缩工具结果：相关性保留 = 首次定位证据 + 高相关性证据 + 最近 N 个；超长结果截断。"""
    if len(tool_results) <= keep_last_n:
        return [
            (n, _truncate_text(t, max_chars_per_result), err, a)
            for n, t, err, a in tool_results
        ]
    first_idx = _find_first_location_index(tool_results)
    keep_last_indices = set(range(len(tool_results) - keep_last_n, len(tool_results)))
    middle_end = len(tool_results) - keep_last_n
    middle_indices = [i for i in range(middle_end) if i != first_idx]
    keywords = relevance_keywords or set()
    scored = [
        (i, _relevance_score_tool_result(tool_results[i][1], keywords))
        for i in middle_indices
    ]
    scored.sort(key=lambda x: -x[1])  # 高相关优先保留
    kept_middle_count = 2  # 除 first_locator 外再保留最多 2 个高相关
    kept_middle = set(scored[i][0] for i in range(min(kept_middle_count, len(scored))))
    kept_indices: set[int] = keep_last_indices | kept_middle
    if first_idx is not None:
        kept_indices.add(first_idx)
    kept = [tool_results[i] for i in sorted(kept_indices)]
    dropped = len(tool_results) - len(kept)
    compacted = [
        (n, _truncate_text(t, max_chars_per_result), err, a)
        for n, t, err, a in kept
    ]
    compacted.insert(
        0,
        (
            "_compact",
            f"[上下文压缩] 已省略 {dropped} 个工具结果，保留首次定位 + 高相关 + 最近 {keep_last_n} 个",
            False,
            None,
        ),
    )
    return compacted


def _optimize_duplicate_tool_results(
    tool_results: list[tuple[str, str, bool, dict | None]],
) -> list[tuple[str, str, bool, dict | None]]:
    """优化重复工具结果：code.read 同文件保留最后一次。"""
    seen_code_read: dict[str, int] = {}  # file_path -> last index
    for i, (name, text, is_err, args) in enumerate(tool_results):
        if name != "code.read" or is_err:
            continue
        fp = (args or {}).get("file_path") if isinstance(args, dict) else None
        if not fp or len(str(fp).strip()) < 2:
            continue
        key = str(fp).strip()
        if key in seen_code_read:
            prev_idx = seen_code_read[key]
            # 将之前的替换为占位
            tool_results[prev_idx] = (
                name,
                f"[code.read] 重复读取 {key}，完整内容见下文最后一次读取",
                False,
                tool_results[prev_idx][3],
            )
        seen_code_read[key] = i
    return tool_results


def _is_file_path_placeholder(val: str | None) -> bool:
    """判断 file_path 是否为占位符（需从 code.search/evidence 结果注入）。"""
    if not val or not isinstance(val, str):
        return True
    s = val.strip()
    placeholders = (
        "上一步", "返回的路径", "code.search", "见上文", "<同上>", "搜索结果",
        "返回的", "相关文件路径", "相关文件", "见上", "同上", "注入",
    )
    if any(p in s for p in placeholders):
        return True
    # 明显为描述性文本（含中文且无路径分隔符）视为占位符
    if re.search(r"[\u4e00-\u9fff]", s) and "/" not in s and "\\" not in s:
        return True
    return len(s) < 3


# 源码扩展名优先于 .class（避免注入 .class 导致 code.read 读到二进制乱码）
_SOURCE_FILE_SUFFIXES = (".java", ".py", ".kt", ".ts", ".js", ".go", ".rs")


def _extract_file_path_from_tool_results(tool_results: list[tuple[str, str, bool, dict | None]]) -> str | None:
    """从 code.search 或 evidence.context_search 结果中提取 file_path。优先 .java/.py 等源码，避免 .class。"""
    for name, text, *_ in tool_results:
        if name not in ("code.search", "evidence.context_search") or not text:
            continue
        try:
            data = json.loads(text)
            if not isinstance(data, dict):
                continue
            # code.search: hits[].file_path，优先源码文件（.java/.py）而非 .class
            hits = data.get("hits") or []
            source_fp: str | None = None
            fallback_fp: str | None = None
            for h in hits:
                if not isinstance(h, dict):
                    continue
                fp = h.get("file_path")
                if not fp or not isinstance(fp, str) or not _looks_like_real_path(fp):
                    continue
                if fallback_fp is None:
                    fallback_fp = fp
                if any(fp.endswith(s) for s in _SOURCE_FILE_SUFFIXES):
                    source_fp = fp
                    break
            if source_fp:
                return source_fp
            if fallback_fp:
                return fallback_fp
            # evidence.context_search: matches[].file_path 或 location.file_path，同样优先源码
            matches = data.get("matches") or []
            match_fallback: str | None = None
            for m in matches:
                if not isinstance(m, dict):
                    continue
                fp = m.get("file_path") or (m.get("location") or {}).get("file_path")
                if not fp or not isinstance(fp, str) or not _looks_like_real_path(fp):
                    continue
                if match_fallback is None:
                    match_fallback = fp
                if any(fp.endswith(s) for s in _SOURCE_FILE_SUFFIXES):
                    return fp
            if match_fallback:
                return match_fallback
        except (json.JSONDecodeError, IndexError, KeyError, TypeError):
            pass
        # 截断后 JSON 可能非法，用正则提取第一个 "file_path":"xxx"
        m = re.search(r'"file_path"\s*:\s*"([^"]+)"', text)
        if m:
            cand = m.group(1)
            if _looks_like_real_path(cand):
                return cand
    return None


def _looks_like_real_path(s: str) -> bool:
    """判断是否像真实文件路径（非占位符描述）。"""
    if not s or len(s) < 2:
        return False
    # 含路径分隔符或常见扩展名
    if "/" in s or "\\" in s or s.endswith((".java", ".py", ".kt", ".ts", ".js", ".go")):
        return True
    # 纯中文或明显描述性文本
    if re.search(r"^[\u4e00-\u9fff\s]+$", s) or "返回" in s or "路径" in s:
        return False
    return True


def _parse_line_from_evidence_need(evidence_need: str | None) -> tuple[int, int] | None:
    """从 evidence_need 解析「类名.java:行号」格式，返回 (start_line, end_line) 用于 code.read。"""
    if not evidence_need or not isinstance(evidence_need, str):
        return None
    m = re.search(r":(\d+)\s*$", evidence_need.strip())
    if not m:
        return None
    line = int(m.group(1))
    # 读取该行前后各约 15 行
    return (max(1, line - 15), line + 15)


def _fill_step_args(
    step: dict,
    event: NormalizedErrorEvent,
    analysis_id: str,
    tool_results_so_far: list[tuple[str, str, bool, dict | None]] | None = None,
    max_evidence_chars: int = 80_000,
    llm_multi_turn_enabled: bool = True,
    evidence_need: str | None = None,
) -> dict:
    """用 event 补全 step.args 中的占位符。analysis.synthesize 时注入 pre_collected_evidence；code.read 时从 code.search 注入 file_path；evidence_need 含「:行号」时注入 start_line/end_line。"""
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
    if tool_name in ("deps.parse_external", "cmd.run_build_analysis") and "repo_id" not in args and "project_root" not in args and service_name:
        args["repo_id"] = service_name
    if tool_name.startswith("lsp.") and "repo_id" not in args and "project_root" not in args and service_name:
        args["repo_id"] = service_name
    if tool_name == "analysis.synthesize":
        if tool_results_so_far:
            parts = []
            for name, text, *_ in tool_results_so_far:
                parts.append(f"[{name}]\n{text}")
            raw_evidence = "\n\n---\n\n".join(parts)
            args["pre_collected_evidence"] = _truncate_text(raw_evidence, max_evidence_chars)
        # 与直连路径一致：始终使用配置的多轮开关，保证输出结构一致
        args["use_multi_turn"] = llm_multi_turn_enabled
    if tool_name in ("analysis.run", "analysis.run_full") and args.get("use_multi_turn") is None:
        args["use_multi_turn"] = False
    if tool_name == "code.read":
        if _is_file_path_placeholder(args.get("file_path")):
            injected = _extract_file_path_from_tool_results(tool_results_so_far or []) if tool_results_so_far else None
            if injected:
                args["file_path"] = injected
                logger.debug(f"[AiOrchestrator] 从 tool_results 注入 file_path: {injected[:80]}...")
            else:
                args.pop("file_path", None)
                logger.warning("[AiOrchestrator] code.read file_path 为占位符但无 code.search/evidence 可注入，已移除")
        # evidence_need 含「类名.java:266」时，注入 start_line/end_line 读取该行附近代码
        if evidence_need and "start_line" not in args and "end_line" not in args:
            line_range = _parse_line_from_evidence_need(evidence_need)
            if line_range:
                args["start_line"], args["end_line"] = line_range
                logger.debug("[AiOrchestrator] 从 evidence_need 注入 start_line=%s end_line=%s", *line_range)
    return args


class AiOrchestrator:
    """AI 驱动分析编排器：Plan -> Act -> Synthesize -> Check。"""

    def __init__(
        self,
        mcp_gateway,
        llm: LLMProvider,
        config: OrchestratorConfig | None = None,
        audit=None,
        hook_hub: HookHub | None = None,
    ):
        self._mcp = mcp_gateway
        self._llm = llm
        self._cfg = config or OrchestratorConfig()
        self._audit = audit
        self._hook_hub = hook_hub
        self._tools_summary: str = ""

    async def ensure_mcp_ready(self) -> None:
        """等待 MCP 连接就绪后再开始分析。"""
        timeout = self._cfg.mcp_ready_timeout_seconds
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            tools = await self._mcp.list_tools()
            if tools:
                return
            await asyncio.sleep(0.5)
        logger.warning("[AiOrchestrator] MCP 连接超时 %.1fs，继续尝试", timeout)

    async def ensure_tools_summary(self) -> None:
        """启动时拉取工具摘要（名称+描述+参数概要），供 Plan 使用。"""
        if self._tools_summary:
            return
        tools = await self._mcp.list_tools()
        self._tools_summary = self._mcp.build_tools_summary(tools, include_params=True)
        logger.info(f"[AiOrchestrator] 已加载 {len(tools)} 个工具摘要（含参数说明）")

    async def _llm_generate_with_retry(self, system: str, user: str) -> str:
        """LLM 调用失败时指数退避重试（2s×2^attempt）。"""
        last_err: Exception | None = None
        for attempt in range(self._cfg.llm_retry_max_attempts):
            try:
                return await self._llm.generate(system=system, user=user)
            except Exception as e:
                last_err = e
                logger.warning("[AiOrchestrator] LLM 调用失败 (attempt %d/%d): %s", attempt + 1, self._cfg.llm_retry_max_attempts, e)
            if attempt < self._cfg.llm_retry_max_attempts - 1:
                delay = 2.0 * (2**attempt)
                logger.info("[AiOrchestrator] %.1fs 后重试...", delay)
                await asyncio.sleep(delay)
        raise last_err or RuntimeError("LLM generate failed")

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
            await self.ensure_mcp_ready()
            await self.ensure_tools_summary()
            # AnalysisStart hook
            if self._hook_hub and self._hook_hub.has_hook("AnalysisStart"):
                out = await self._hook_hub.execute_analysis_start(
                    analysis_id, service_name=event.service_name,
                    task_metadata={"query_key": event.query_key},
                )
                if out.cancel:
                    raise RuntimeError(f"AnalysisStart hook 取消分析: {out.error_message or '用户取消'}")
            try:
                return await _run_body()
            finally:
                # AnalysisComplete hook（无论成功或异常都调用）
                if self._hook_hub and self._hook_hub.has_hook("AnalysisComplete"):
                    await self._hook_hub.execute_analysis_complete(
                        analysis_id, service_name=event.service_name,
                        task_metadata={"query_key": event.query_key},
                    )

        async def _run_body() -> AnalysisReport:
            logger.info("[AiOrchestrator] 编排模式=%s, analysis_id=%s", self._cfg.orchestration_mode, analysis_id)
            if self._cfg.orchestration_mode == "tool_use_loop":
                return await self._run_tool_use_loop(event, analysis_id)

            prev_report: AnalysisReport | None = None
            evidence_needs: list[str] = []
            tool_plan_hint: str = ""
            prev_tool_results: list[tuple[str, str, bool, dict | None]] = []

            for round_num in range(1, self._cfg.max_analysis_rounds + 1):
                logger.info(f"[AiOrchestrator] 第 {round_num}/{self._cfg.max_analysis_rounds} 轮分析")

                if round_num == 1:
                    plan = await self._plan(event, analysis_id)
                else:
                    # 长对话时压缩 prev_tool_results
                    to_plan = prev_tool_results
                    if _should_compact_context(
                        round_num,
                        prev_tool_results,
                        self._cfg.compact_context_after_rounds,
                        self._cfg.compact_context_threshold_chars,
                        self._cfg.compact_context_threshold_tokens,
                    ):
                        to_plan = _compact_tool_results(
                            prev_tool_results,
                            keep_last_n=self._cfg.compact_context_keep_last_n,
                            relevance_keywords=extract_relevance_keywords(event.error_log or ""),
                        )
                        logger.info(
                            "[AiOrchestrator] 上下文压缩：保留最近 %d 个工具结果",
                            self._cfg.compact_context_keep_last_n,
                        )
                    plan = await self._plan_next_round(
                        event, analysis_id, prev_report, evidence_needs, tool_plan_hint,
                        prev_tool_results=to_plan,
                        round_num=round_num,
                    )

                if not plan or not plan.get("steps"):
                    if prev_report is not None:
                        return prev_report
                    raise RuntimeError("Plan 为空或没有 steps")

                steps = plan["steps"][: self._cfg.max_tool_calls]
                steps = _reorder_steps_cline_mode(steps)
                # Plan 阶段过滤被限制的工具
                if PLAN_RESTRICTED_TOOLS:
                    orig_len = len(steps)
                    steps = [s for s in steps if s.get("tool_name") not in PLAN_RESTRICTED_TOOLS]
                    if len(steps) < orig_len:
                        logger.info(
                            "[AiOrchestrator] Plan 阶段过滤受限工具 %s，剩余 %d 步",
                            PLAN_RESTRICTED_TOOLS,
                            len(steps),
                        )
                if not steps and prev_report is not None:
                    return prev_report
                tool_results: list[tuple[str, str, bool, dict | None]] = []
                # evidence_ctx 供 evidence.context_search 查询，跨轮累积；token 预算 + 相关性关键词
                max_tokens = self._cfg.max_evidence_total_tokens or (self._cfg.max_evidence_total_chars // 2)
                relevance_kw = extract_relevance_keywords(event.error_log or "")
                evidence_ctx = EvidenceContext(
                    max_total_chars=self._cfg.max_evidence_total_chars,
                    max_total_tokens=max_tokens,
                    relevance_keywords=relevance_kw,
                )
                evidence_ctx.from_tool_results(prev_tool_results)
                context = {
                    "trace_id": analysis_id,
                    "analysis_id": analysis_id,
                    "evidence_ctx": evidence_ctx,
                }
                failure_counts: dict[str, int] = {}
                need_more_evidence_triggered = False

                for i, step in enumerate(steps):
                    tool_name = step.get("tool_name")
                    if not tool_name:
                        continue
                    args = _fill_step_args(
                        step, event, analysis_id,
                        tool_results_so_far=tool_results,
                        max_evidence_chars=self._cfg.max_evidence_total_chars,
                        llm_multi_turn_enabled=self._cfg.llm_multi_turn_enabled,
                    )
                    # PreToolUse 传入实际将执行的 args（填充后），cancel 时跳过该工具
                    if self._hook_hub and self._hook_hub.has_hook("PreToolUse"):
                        pre_out = await self._hook_hub.execute_pre_tool_use(
                            analysis_id, tool_name, args,
                            service_name=event.service_name,
                        )
                        if pre_out.cancel:
                            logger.info("[AiOrchestrator] PreToolUse 取消工具 %s: %s", tool_name, pre_out.error_message or "")
                            continue
                    t0 = time.perf_counter()
                    result = await self._call_tool_with_retry(
                        tool_name, args, context, event, analysis_id,
                        failure_count=failure_counts.get(tool_name, 0),
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
                        err_msg = (result.content[0].text or "unknown") if result.content else "unknown"
                        # PostToolUse hook（失败时也调用）
                        if self._hook_hub and self._hook_hub.has_hook("PostToolUse"):
                            await self._hook_hub.execute_post_tool_use(
                                analysis_id, tool_name, args,
                                result=err_msg[:2000], success=False,
                                execution_time_ms=int(elapsed * 1000),
                                service_name=event.service_name,
                            )
                        failure_counts[tool_name] = failure_counts.get(tool_name, 0) + 1
                        err_code = result.errorCode or "INTERNAL_ERROR"
                        logger.warning(
                            f"[AiOrchestrator] 工具调用失败: {tool_name}, error_code={err_code}, message={err_msg[:200]}"
                        )
                        if failure_counts[tool_name] >= self._cfg.mistake_limit:
                            raise RuntimeError(
                                f"工具 {tool_name} 连续失败 {failure_counts[tool_name]} 次（mistake_limit={self._cfg.mistake_limit}），中止分析"
                            )
                        raise RuntimeError(f"Tool {tool_name} failed [{err_code}]: {err_msg}")

                    failure_counts[tool_name] = 0  # 成功时重置
                    text = (result.content[0].text or "") if result.content else ""
                    repro = _build_repro_hint(event, tool_name)
                    text = _truncate_tool_result_struct(
                        text, self._cfg.tool_result_max_chars, tool_name, repro_hint=repro
                    )
                    # PostToolUse hook
                    if self._hook_hub and self._hook_hub.has_hook("PostToolUse"):
                        await self._hook_hub.execute_post_tool_use(
                            analysis_id, tool_name, args,
                            result=text, success=True,
                            execution_time_ms=int(elapsed * 1000),
                            service_name=event.service_name,
                        )
                    # 计划 5.2：保留可复现查询参数（截断时供 Synthesize 引用）
                    tool_results.append((tool_name, text, False, args))
                    # 更新 evidence_ctx 供后续 evidence.context_search 查询
                    if tool_name != "evidence.context_search":
                        evidence_ctx.add(tool_name, text, key_hint=args.get("query", ""))
                    elif text:
                        try:
                            parsed = json.loads(text)
                            if parsed.get("found") and parsed.get("matches"):
                                q = args.get("query", "")
                                evidence_text = evidence_ctx.to_evidence_text(q)
                                if evidence_text and evidence_text != text:
                                    tool_results[-1] = (tool_name, evidence_text, False, args)
                        except Exception as e:
                            logger.debug(
                                "[AiOrchestrator] evidence.context_search 结果解析失败 analysis_id=%s tool=%s: %s",
                                analysis_id, tool_name, type(e).__name__,
                            )

                    if tool_name in ("analysis.run", "analysis.run_full", "analysis.synthesize"):
                        try:
                            parsed = json.loads(text)
                            report = self._report_from_analysis_run(parsed, event, analysis_id)
                            r, _ = self._check_and_sanitize(report, event, tool_results)
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
                        except Exception as e:
                            logger.warning(
                                "[AiOrchestrator] analysis.run/run_full/synthesize JSON 解析失败 analysis_id=%s tool=%s: %s",
                                analysis_id, tool_name, type(e).__name__,
                            )

                if need_more_evidence_triggered:
                    report, hit_depth_limit = await self._collect_evidence_recursive(
                        event, analysis_id, evidence_needs, tool_results, prev_report, depth=0,
                        evidence_ctx=evidence_ctx,
                        failure_counts=failure_counts,
                    )
                    if hit_depth_limit:
                        logger.info("[AiOrchestrator] 证据收集已达最大递归深度，结束")
                    return report

                report = await self._synthesize(event, analysis_id, tool_results)
                # 链路追问：_synthesize 返回 need_more_evidence 时触发递归收集（参考 Cline tool_use 循环）
                if report.need_more_evidence:
                    evidence_needs = [str(x).strip() for x in report.need_more_evidence if str(x).strip()][:6]
                    if evidence_needs:
                        logger.info(
                            "[AiOrchestrator] Synthesize 返回 NEED_MORE_EVIDENCE，触发链路追问: %s...",
                            evidence_needs[:3],
                        )
                        report, hit_depth_limit = await self._collect_evidence_recursive(
                            event, analysis_id, evidence_needs, tool_results, report, depth=0,
                            evidence_ctx=evidence_ctx,
                            failure_counts=failure_counts,
                        )
                        if hit_depth_limit:
                            logger.info("[AiOrchestrator] 证据收集已达最大递归深度，结束")
                        return report
                report, needs_extra = self._check_and_sanitize(report, event, tool_results)
                if needs_extra and self._cfg.check_extra_tool_calls > 0 and len(tool_results) < self._cfg.max_tool_calls:
                    extra_report = await self._try_check_extra_tools(event, analysis_id, tool_results)
                    if extra_report is not None:
                        report = extra_report
                        report, needs_extra = self._check_and_sanitize(report, event, tool_results)

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
                        "confidence": decision.get("confidence"),
                        "degraded_modes": decision.get("degraded_modes"),
                    })
                if self._cfg.checkpoint_enabled and self._audit:
                    self._audit.log({
                        "event": "orchestrator_checkpoint",
                        "analysis_id": analysis_id,
                        "round_num": round_num,
                        "report_summary": (report.summary or "")[:200],
                        "tool_count": len(tool_results),
                    })

                if not decision or not decision.get("continue_analysis"):
                    return report
                if round_num >= self._cfg.max_analysis_rounds:
                    logger.info(f"[AiOrchestrator] 已达最大轮数 {self._cfg.max_analysis_rounds}，结束分析")
                    return report

                prev_report = report
                prev_tool_results = tool_results
                evidence_needs = decision.get("next_round_evidence_needs") or []
                tool_plan = decision.get("next_round_tool_plan") or {}
                tool_plan_hint = tool_plan.get("hint", "") or str(tool_plan.get("suggested_tools", []))
                deg = decision.get("degraded_modes")
                if deg and isinstance(deg, list):
                    logger.info("[AiOrchestrator] Check 返回 degraded_modes: %s", deg[:5])

            return report

        return await asyncio.wait_for(_run(), timeout=timeout)

    async def _call_tool_with_retry(
        self,
        tool_name: str,
        args: dict,
        context: dict,
        event: NormalizedErrorEvent,
        analysis_id: str,
        failure_count: int = 0,
    ) -> ToolResult:
        """调用工具，若失败则由错误判断 AI 分析错误原因、修正参数后重试一次。"""
        result = await self._mcp.call_tool(tool_name, args, context)
        if not result.isError:
            return result

        err_code = result.errorCode or "INTERNAL_ERROR"
        err_msg = (result.content[0].text or "unknown") if result.content else "unknown"

        # 不可修正的错误码直接返回，不调用错误判断 AI（Cline 风格：TOOL_NOT_FOUND、DEPENDENCY_UNAVAILABLE 建议 abort）
        if err_code in UNRECOVERABLE_ERROR_CODES:
            logger.info(f"[AiOrchestrator] 工具 {tool_name} 失败 [{err_code}]，不可修正，跳过错误判断 AI")
            return result

        logger.info(f"[AiOrchestrator] 工具 {tool_name} 调用失败 [{err_code}]，尝试错误判断 AI 分析并修正: {err_msg[:150]}")

        # 渐进式错误提示（参考 Cline writeToFileMissingContentError：按 1/2/3+ 次分级）
        if failure_count >= 2:
            progressive_hint = (
                f"【重要】该工具已连续失败 {failure_count + 1} 次。"
                "请仔细检查参数或考虑 abort；若为 TOOL_TIMEOUT，可尝试简化参数、缩小范围。"
            )
        elif failure_count == 1:
            progressive_hint = "【提示】该工具已第 2 次失败，请仔细核对参数后再修正。"
        else:
            progressive_hint = ""

        try:
            param_name = extract_missing_param_from_error(err_msg) if err_code == "INVALID_PARAMS" else None
            formatted_err = format_tool_error(
                err_msg[:500],
                tool_name=tool_name,
                error_code=err_code,
                param_name=param_name,
            )
            prompt_ctx = AIPromptContext(
                tool_name=tool_name,
                error_code=err_code,
                error_msg=formatted_err,
                args=json.dumps(args, ensure_ascii=False),
                progressive_hint=progressive_hint,
                service_name=event.service_name,
                query_key=event.query_key,
                analysis_id=analysis_id,
                error_log_preview=_truncate_text(event.error_log, 500),
            )
            user = build_fix_args_user_prompt(prompt_ctx)
            raw = await self._llm_generate_with_retry(
                prompts.AI_ORCHESTRATOR_FIX_ARGS_SYSTEM,
                user,
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
                (
                    "correlation.get_info",
                    {
                        "service_name": event.service_name,
                        "error_log": _truncate_text(event.error_log, 500),
                        "query_key": event.query_key,
                    },
                )
            )
        if "index.get_status" not in called_tools:
            extra_tools.append(("index.get_status", {"service_name": event.service_name}))

        context = {"trace_id": analysis_id, "analysis_id": analysis_id}
        for tool_name, args in extra_tools[: min(2, self._cfg.check_extra_tool_calls)]:
            result = await self._mcp.call_tool(tool_name, args, context)
            if result.isError:
                continue
            text = (result.content[0].text or "") if result.content else ""
            repro = _build_repro_hint(event, tool_name)
            truncated = _truncate_tool_result_struct(
                text, self._cfg.tool_result_max_chars, tool_name, repro_hint=repro
            )
            tool_results.append((tool_name, truncated, False, args))
            report = await self._synthesize(event, analysis_id, tool_results)
            report, needs_extra = self._check_and_sanitize(report, event, tool_results)
            if not needs_extra:
                return report
        return None

    async def _run_tool_use_loop(
        self, event: NormalizedErrorEvent, analysis_id: str
    ) -> AnalysisReport:
        """Cline/Cursor 风格：模型自主决定 tool call，无 tool_use 时输出 JSON 报告。"""
        logger.info("[AiOrchestrator] tool_use_loop 模式启动，analysis_id=%s", analysis_id)
        if not hasattr(self._llm, "generate_with_tools"):
            raise RuntimeError("tool_use_loop 模式需要 LLM 支持 generate_with_tools")

        ctx = await self._discover_context(event, analysis_id)
        tools_raw = await self._mcp.list_tools()
        tools = [
            _mcp_tool_schema_to_openai_function(t)
            for t in tools_raw
            if t.name not in _TOOL_USE_LOOP_EXCLUDED_TOOLS
        ]
        if not tools:
            raise RuntimeError("tool_use_loop 无可用工具")

        user_msg = prompts.TOOL_USE_LOOP_USER.format(
            service_name=event.service_name,
            error_log=_truncate_text(event.error_log, 4000),
            index_preview=ctx.index_preview or "（无）",
            correlation_preview=ctx.correlation_preview or "（无）",
        )
        messages: list[dict[str, Any]] = [{"role": "user", "content": user_msg}]
        context = {"trace_id": analysis_id, "analysis_id": analysis_id, "evidence_ctx": EvidenceContext()}

        last_err: Exception | None = None
        for attempt in range(self._cfg.llm_retry_max_attempts):
            try:
                return await self._tool_use_loop_iterate(
                    messages, tools, context, event, analysis_id
                )
            except Exception as e:
                last_err = e
                logger.warning("[AiOrchestrator] tool_use_loop 失败 (attempt %d/%d): %s", attempt + 1, self._cfg.llm_retry_max_attempts, e)
            if attempt < self._cfg.llm_retry_max_attempts - 1:
                delay = 2.0 * (2**attempt)
                await asyncio.sleep(delay)
        raise last_err or RuntimeError("tool_use_loop failed")

    async def _tool_use_loop_iterate(
        self,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]],
        context: dict[str, Any],
        event: NormalizedErrorEvent,
        analysis_id: str,
        *,
        iteration: int = 0,
    ) -> AnalysisReport:
        """执行单次 tool_use 循环：调用 LLM → 若有 tool_calls 则执行并追加消息 → 递归；否则解析 content 为报告。"""
        max_iter = self._cfg.max_analysis_rounds  # tool_use_loop 用 max_analysis_rounds 作为迭代上限
        if iteration >= max_iter:
            raise RuntimeError(f"tool_use_loop 超过最大迭代次数 {max_iter}，强制结束")
        content, tool_calls = await self._llm.generate_with_tools(
            system=prompts.TOOL_USE_LOOP_SYSTEM,
            messages=messages,
            tools=tools,
        )

        if tool_calls:
            logger.info(
                "[AiOrchestrator] tool_use_loop 收到 %d 个 tool_calls: %s",
                len(tool_calls),
                [tc.get("name") for tc in tool_calls],
            )
            assistant_msg: dict[str, Any] = {
                "role": "assistant",
                "content": content or "",
                "tool_calls": [
                    {"id": tc.get("id", ""), "type": "function", "function": {"name": tc.get("name", ""), "arguments": tc.get("arguments", "{}")}}
                    for tc in tool_calls
                ],
            }
            messages.append(assistant_msg)

            for tc in tool_calls:
                tool_id = tc.get("id", "")
                tool_name = tc.get("name", "")
                args_str = tc.get("arguments", "{}")
                try:
                    args = json.loads(args_str) if isinstance(args_str, str) else (args_str or {})
                except json.JSONDecodeError:
                    args = {}

                if self._hook_hub and self._hook_hub.has_hook("PreToolUse"):
                    pre_out = await self._hook_hub.execute_pre_tool_use(
                        analysis_id, tool_name, args,
                        service_name=event.service_name,
                    )
                    if pre_out.cancel:
                        continue

                result = await self._mcp.call_tool(tool_name, args, context)
                text = (result.content[0].text or "") if result.content else ""
                if result.isError:
                    text = format_tool_error(text, error_code=result.errorCode, tool_name=tool_name)
                repro = _build_repro_hint(event, tool_name)
                truncated = _truncate_tool_result_struct(
                    text, self._cfg.tool_result_max_chars, tool_name, repro_hint=repro
                )

                messages.append({
                    "role": "tool",
                    "tool_call_id": tool_id,
                    "content": truncated,
                })

            return await self._tool_use_loop_iterate(
                messages, tools, context, event, analysis_id,
                iteration=iteration + 1,
            )

        if not content or not content.strip():
            raise RuntimeError("tool_use_loop: 模型未返回 tool_calls 且 content 为空")

        logger.info("[AiOrchestrator] tool_use_loop 模型输出最终 JSON，结束循环")
        parsed = parse_json_markdown(content)
        if not isinstance(parsed, dict):
            raise RuntimeError("tool_use_loop: 模型未返回有效 JSON")
        report = self._report_from_parsed(parsed, event, analysis_id)
        report, _ = self._check_and_sanitize(report, event, None)
        return report

    async def _discover_context(self, event: NormalizedErrorEvent, analysis_id: str) -> DiscoveredContext:
        """上下文发现：预取 index/correlation，解析引用。传完整 error_log 让关键行优先采样生效，避免截断漏检 trace_id/栈。"""
        refs = discover_refs_from_error_log(event.error_log or "", max_preview_chars=6000)
        error_preview = _truncate_text(event.error_log, 2000)
        hints = build_hints_for_plan(refs)

        index_preview = ""
        correlation_preview = ""
        context = {"trace_id": analysis_id, "analysis_id": analysis_id}

        try:
            result = await self._mcp.call_tool(
                "index.get_status",
                {"service_name": event.service_name},
                context,
            )
            if not result.isError and result.content:
                text = result.content[0].text if result.content else ""
                index_preview = _truncate_text(text, 3000)
        except Exception as e:
            logger.debug("[AiOrchestrator] 预取 index.get_status 失败: %s", e)

        trace_id = refs.get("trace_id", [None])[0] if refs.get("trace_id") else None
        if trace_id:
            try:
                result = await self._mcp.call_tool(
                    "correlation.get_info",
                    {
                        "service_name": event.service_name,
                        "error_log": error_preview,
                        "query_key": event.query_key,
                    },
                    context,
                )
                if not result.isError and result.content:
                    text = result.content[0].text if result.content else ""
                    correlation_preview = _truncate_text(text, 2000)
            except Exception as e:
                logger.debug("[AiOrchestrator] 预取 correlation.get_info 失败: %s", e)

        return DiscoveredContext(
            index_preview=index_preview,
            correlation_preview=correlation_preview,
            extracted_refs=refs,
            hints_for_plan=hints,
        )

    async def _plan(self, event: NormalizedErrorEvent, analysis_id: str) -> dict:
        """Plan 阶段：LLM 生成工具调用计划（首轮）。上下文发现 → 注入 → 规划。"""
        error_preview = _truncate_text(event.error_log, 2000)
        ctx = await self._discover_context(event, analysis_id)
        focus = build_focus_chain(1, self._cfg.max_analysis_rounds, [])
        prompt_ctx = AIPromptContext(
            service_name=event.service_name,
            query_key=event.query_key,
            analysis_id=analysis_id,
            error_log=error_preview,
            tools_summary=self._tools_summary,
            index_preview=ctx.index_preview or "（未预取，Plan 中可先调用 index.get_status 获取）",
            correlation_preview=ctx.correlation_preview or "（无 trace_id 或未预取，可跳过 correlation.get_info）",
            discovered_hints=ctx.hints_for_plan,
            focus_chain=focus,
        )
        user = build_plan_user_prompt(prompt_ctx)
        raw = await self._llm_generate_with_retry(prompts.AI_ORCHESTRATOR_PLAN_SYSTEM, user)
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
        prev_tool_results: list[tuple[str, str, bool, dict | None]] | None = None,
        round_num: int = 2,
    ) -> dict:
        """Plan 阶段：后续轮，基于上一轮报告与证据需求。注入路径上下文。"""
        rule_hint = ""
        completed = []
        if prev_tool_results:
            paths = extract_paths_from_tool_results(prev_tool_results)
            rule_hint = build_rule_context_hint(paths)
            called = {n for n, *_ in prev_tool_results}
            if "index.get_status" in called or "correlation.get_info" in called:
                completed.append("获取上下文")
            if "code.search" in called or "evidence.context_search" in called:
                completed.append("定位代码")
            if "code.read" in called:
                completed.append("收集证据")
            if "analysis.synthesize" in called or "analysis.run_full" in called:
                completed.append("分析根因")
        extra_hint = f"\n{rule_hint}" if rule_hint else ""
        focus = build_focus_chain(
            round_num=round_num,
            max_rounds=self._cfg.max_analysis_rounds,
            completed_steps=completed,
        )
        prompt_ctx = AIPromptContext(
            service_name=event.service_name,
            error_log=_truncate_text(event.error_log, 1000),
            previous_summary=prev_report.summary or "无",
            previous_hypotheses="; ".join((prev_report.hypotheses or [])[:5]) or "无",
            evidence_needs="\n".join(f"- {e}" for e in evidence_needs) if evidence_needs else "无",
            tool_plan_hint=(tool_plan_hint or "无") + extra_hint,
            tools_summary=self._tools_summary,
            focus_chain=focus,
        )
        user = build_plan_next_round_user_prompt(prompt_ctx)
        raw = await self._llm_generate_with_retry(
            prompts.AI_ORCHESTRATOR_PLAN_NEXT_ROUND_SYSTEM, user
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
        raw = await self._llm_generate_with_retry(
            prompts.AI_ORCHESTRATOR_PLAN_SINGLE_EVIDENCE_NEED_SYSTEM, user
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
        failure_counts: dict[str, int] | None = None,
    ) -> tuple[AnalysisReport, bool]:
        """
        对每个 NEED_MORE_EVIDENCE 建立子计划并执行，递归直到收集不到证据或达到深度限制。
        优先从 evidence_ctx 查找已有证据，避免重复调用工具。
        返回 (report, hit_depth_limit)。
        """
        context = {"trace_id": analysis_id, "analysis_id": analysis_id}
        failure_counts = failure_counts or {}
        collected = list(tool_results)
        if evidence_ctx is None:
            max_tokens = self._cfg.max_evidence_total_tokens or (self._cfg.max_evidence_total_chars // 2)
            relevance_kw = extract_relevance_keywords(event.error_log or "")
            evidence_ctx = EvidenceContext(
                max_total_chars=self._cfg.max_evidence_total_chars,
                max_total_tokens=max_tokens,
                relevance_keywords=relevance_kw,
            )
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
                    llm_multi_turn_enabled=self._cfg.llm_multi_turn_enabled,
                    evidence_need=evidence_need,
                )
                if tool_name == "evidence.context_search" and "query" not in args:
                    args["query"] = evidence_need
                try:
                    result = await self._call_tool_with_retry(
                        tool_name, args, context, event, analysis_id,
                        failure_count=failure_counts.get(tool_name, 0),
                    )
                    if result.isError:
                        failure_counts[tool_name] = failure_counts.get(tool_name, 0) + 1
                        continue
                    text = (result.content[0].text or "") if result.content else ""
                    repro = _build_repro_hint(event, tool_name)
                    text = _truncate_tool_result_struct(
                        text, self._cfg.tool_result_max_chars, tool_name, repro_hint=repro
                    )
                    failure_counts[tool_name] = 0
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
                        except Exception as e:
                            logger.debug(
                                "[AiOrchestrator] 子计划 evidence.context_search 解析失败 analysis_id=%s: %s",
                                analysis_id, type(e).__name__,
                            )
                except Exception as e:
                    logger.warning(f"[AiOrchestrator] 子计划步骤 {tool_name} 执行失败: {e}")

        if not collected:
            return fallback_report, False

        step = {
            "tool_name": "analysis.synthesize",
            "args": {"error_event": {"service_name": event.service_name, "error_log": "见上文", "query_key": event.query_key}},
        }
        args = _fill_step_args(
            step, event, analysis_id,
            tool_results_so_far=collected,
            max_evidence_chars=self._cfg.max_evidence_total_chars,
            llm_multi_turn_enabled=self._cfg.llm_multi_turn_enabled,
        )
        result = await self._mcp.call_tool("analysis.synthesize", args, context)
        if result.isError:
            report = await self._synthesize(event, analysis_id, collected)
            return self._check_and_sanitize(report, event, collected)[0], depth >= self._cfg.max_evidence_collection_depth

        text = (result.content[0].text or "") if result.content else "{}"
        try:
            parsed = json.loads(text)
            report = self._report_from_analysis_run(parsed, event, analysis_id)
            r, _ = self._check_and_sanitize(report, event, collected)
            need_more = parsed.get("NEED_MORE_EVIDENCE") or parsed.get("need_more_evidence")
            if isinstance(need_more, list) and need_more and depth < self._cfg.max_evidence_collection_depth:
                new_needs = [str(x).strip() for x in need_more if str(x).strip()][:6]
                if new_needs:
                    logger.info(
                        f"[AiOrchestrator] 证据收集递归 depth={depth + 1}，新需求: {new_needs[:3]}..."
                    )
                    return await self._collect_evidence_recursive(
                        event, analysis_id, new_needs, collected, r, depth + 1, evidence_ctx,
                        failure_counts=failure_counts,
                    )
            return r, depth >= self._cfg.max_evidence_collection_depth
        except Exception as e:
            logger.warning(
                "[AiOrchestrator] 证据收集 analysis.run JSON 解析失败 analysis_id=%s tool=analysis.synthesize: %s",
                analysis_id, type(e).__name__,
            )
            report = await self._synthesize(event, analysis_id, collected)
            return self._check_and_sanitize(report, event, collected)[0], depth >= self._cfg.max_evidence_collection_depth

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
        prompt_ctx = AIPromptContext(
            service_name=event.service_name,
            round_num=round_num,
            max_rounds=self._cfg.max_analysis_rounds,
            report_summary=report.summary or "无",
            hypotheses="; ".join((report.hypotheses or [])[:5]) or "无",
            suggestions="; ".join((report.suggestions or [])[:5]) or "无",
            tool_results_preview=_truncate_text(results_text, 2000),
        )
        user = build_next_round_decision_user_prompt(prompt_ctx)
        try:
            raw = await self._llm_generate_with_retry(
                prompts.AI_ORCHESTRATOR_NEXT_ROUND_SYSTEM, user
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
        optimized = _optimize_duplicate_tool_results(list(tool_results))
        parts = []
        for name, text, _, args in optimized:
            part = f"[{name}]"
            if args:
                args_brief = json.dumps(args, ensure_ascii=False)[:300]
                part += f"\n【可复现参数】{args_brief}"
            part += f"\n{text}"
            parts.append(part)
        results_text = "\n\n---\n\n".join(parts)
        max_results_chars = 12_000
        truncated = (
            _truncate_multilevel(results_text, max_results_chars)
            if len(results_text) > max_results_chars
            else results_text
        )
        prompt_ctx = AIPromptContext(
            service_name=event.service_name,
            error_log=_truncate_text(event.error_log, 1500),
            tool_results=truncated,
        )
        user = build_synthesize_user_prompt(prompt_ctx)
        raw = await self._llm_generate_with_retry(prompts.AI_ORCHESTRATOR_SYNTHESIZE_SYSTEM, user)
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
        """从 LLM 解析结果构造 AnalysisReport。含 need_more_evidence 以支持链路追问（参考 Cline tool_use 循环）。"""
        if not isinstance(parsed, dict):
            parsed = {}
        summary = parsed.get("summary")
        if isinstance(summary, dict):
            summary = summary.get("direct_cause") or summary.get("summary") or str(summary)
        summary = str(summary or "分析完成")
        need_more = parsed.get("NEED_MORE_EVIDENCE") or parsed.get("need_more_evidence")
        need_more_evidence = (
            [str(x).strip() for x in need_more if str(x).strip()][:6]
            if isinstance(need_more, list) and need_more
            else None
        )
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
            need_more_evidence=need_more_evidence,
        )

    def _check_and_sanitize(
        self,
        report: AnalysisReport,
        event: NormalizedErrorEvent,
        tool_results: list[tuple[str, str, bool, dict | None]] | None = None,
    ) -> tuple[AnalysisReport, bool]:
        """
        Check 阶段：自检与安全脱敏。
        - 覆盖性：summary 非空、有 service_name、关键日志证据
        - 可复现性：correlation_id、query_key 等可追溯信息补全
        - 一致性：有勘探证据但结论泛化时标记 needs_extra
        - 安全性：脱敏 AK/SK、token、连接串等
        返回 (report, needs_extra)：needs_extra 为 True 时建议追加 tool calls 补齐。
        """
        summary = redact_sensitive(report.summary or "分析完成")
        hypotheses = [redact_sensitive(str(h)) for h in (report.hypotheses or [])]
        suggestions = [redact_sensitive(str(s)) for s in (report.suggestions or [])]
        business_impact = redact_sensitive(report.business_impact) if report.business_impact else None

        # 可复现性：补全 correlation_id（从 event 继承，便于 ingest→queue→analyze 贯通）
        correlation_id = report.correlation_id or event.correlation_id

        diagnosis = _build_diagnosis_summary(tool_results)
        sanitized = report.model_copy(
            update={
                "summary": summary,
                "hypotheses": hypotheses,
                "suggestions": suggestions,
                "business_impact": business_impact,
                "correlation_id": correlation_id,
                "diagnosis_summary": diagnosis or report.diagnosis_summary,
            }
        )

        needs_extra = False
        # 覆盖性检查（计划 5.2：错误签名、关键日志证据、repo_id/服务名）
        if not report.service_name:
            needs_extra = True
        elif (not summary or summary == "分析完成") and not hypotheses and not suggestions:
            needs_extra = True

        # 可复现性检查：若有 query_key/trace_id 但结论过于泛化，建议补充
        if not needs_extra and (event.query_key or event.correlation_id):
            if summary and len(summary.strip()) < 30 and not hypotheses:
                needs_extra = True

        # 一致性检查：有充足勘探证据但结论泛化，可能证据未充分利用
        if not needs_extra and tool_results:
            exploration_tools = {"code.search", "code.read", "evidence.context_search", "correlation.get_info"}
            exploration_count = sum(1 for n, *_ in tool_results if n in exploration_tools)
            if exploration_count >= 2 and len((summary or "").strip()) < 50 and not hypotheses:
                needs_extra = True

        return sanitized, needs_extra
