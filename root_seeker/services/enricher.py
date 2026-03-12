from __future__ import annotations

import json
import logging
import re
from dataclasses import dataclass
from datetime import timedelta

from root_seeker.domain import LogBundle, NormalizedErrorEvent
from root_seeker.providers.llm import LLMProvider
from root_seeker.providers.sls import CloudLogProvider
from root_seeker.providers.trace_chain import TraceChainProvider
from root_seeker.sql_templates import SqlTemplateRegistry
from root_seeker import prompts
from root_seeker.utils import parse_json_markdown

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class EnrichmentConfig:
    time_window_seconds: int = 300
    trace_chain_enabled: bool = True  # 是否启用调用链日志查询
    trace_chain_time_window_seconds: int = 300  # 调用链查询时间窗口（最大5分钟，300秒）


class LogEnricher:
    def __init__(
        self,
        *,
        registry: SqlTemplateRegistry,
        provider: CloudLogProvider,
        cfg: EnrichmentConfig | None = None,
        llm: LLMProvider | None = None,  # 用于提取 trace_id
        trace_chain_provider: TraceChainProvider | None = None,  # 用于查询 trace_id 日志链
    ):
        self._registry = registry
        self._provider = provider
        self._cfg = cfg or EnrichmentConfig()
        self._llm = llm
        self._trace_chain_provider = trace_chain_provider

    async def enrich(self, event: NormalizedErrorEvent) -> LogBundle:
        logger.info(f"[LogEnricher] 开始补全日志，service={event.service_name}, query_key={event.query_key}")
        
        # 1. 基础日志补全（原有逻辑）
        base_bundle = await self._enrich_base(event)
        logger.info(f"[LogEnricher] 基础日志补全完成，记录数={len(base_bundle.records)}")

        # 2. 如果启用调用链查询，尝试提取 trace_id/request_id 并查询调用链
        if self._cfg.trace_chain_enabled and self._trace_chain_provider is not None:
            logger.info("[LogEnricher] 调用链查询已启用，开始提取 trace_id/request_id")
            trace_id, request_id = await self._extract_trace_ids(event)
            
            # 无论是否提取到，都输出日志
            if trace_id or request_id:
                logger.info(f"[LogEnricher] ✅ 提取到 trace_id={trace_id}, request_id={request_id}，开始查询调用链日志")
                chain_bundle = await self._enrich_chain(event, trace_id, request_id)
                logger.info(f"[LogEnricher] 调用链日志查询完成，记录数={len(chain_bundle.records)}")
                
                if chain_bundle.records:
                    merged = self._merge_bundles(base_bundle, chain_bundle)
                    logger.info(f"[LogEnricher] 日志合并完成，总记录数={len(merged.records)}")
                    return merged
                else:
                    logger.info("[LogEnricher] 调用链日志为空，返回基础日志")
            else:
                logger.info("[LogEnricher] ⚠️ 未提取到 trace_id/request_id，跳过调用链查询")
        elif self._cfg.trace_chain_enabled:
            logger.info("[LogEnricher] 调用链查询已启用但未配置 trace_chain_provider，跳过调用链查询")
        else:
            logger.info("[LogEnricher] 调用链查询未启用")

        return base_bundle

    async def _enrich_base(self, event: NormalizedErrorEvent) -> LogBundle:
        """基础日志补全（原有逻辑）"""
        query_key = event.query_key or "default_error_context"
        template = None
        try:
            template = self._registry.get(query_key)
        except KeyError:
            # 如果配置的 query_key 不存在，尝试使用默认值
            if query_key != "default_error_context":
                try:
                    template = self._registry.get("default_error_context")
                    query_key = "default_error_context"
                except KeyError:
                    # 如果连默认值都没有，返回空 LogBundle
                    return LogBundle(
                        query_key=query_key,
                        records=[],
                        raw=None,
                    )
            else:
                return LogBundle(
                    query_key=query_key,
                    records=[],
                    raw=None,
                )

        start = event.timestamp - timedelta(seconds=self._cfg.time_window_seconds)
        end = event.timestamp + timedelta(seconds=self._cfg.time_window_seconds)
        from_ts = int(start.timestamp())
        to_ts = int(end.timestamp())
        params = {
            "service_name": event.service_name,
            "error_log": event.error_log,
            "start_ts": from_ts,
            "end_ts": to_ts,
        }
        query = template.render(params) if template is not None else ""
        err_preview = (event.error_log or "")[:200]
        logger.info(
            f"[LogEnricher] 基础日志补全请求参数: query_key={query_key}, from_ts={from_ts}, to_ts={to_ts}, "
            f"service_name={event.service_name}, error_log_preview={err_preview!r}..."
        )
        logger.debug(f"[LogEnricher] 基础日志补全 SQL: {query[:500]}..." if len(query) > 500 else f"[LogEnricher] 基础日志补全 SQL: {query}")
        return await self._provider.query(
            query_key=query_key,
            query=query,
            from_ts=from_ts,
            to_ts=to_ts,
        )

    async def _extract_trace_ids(self, event: NormalizedErrorEvent) -> tuple[str | None, str | None]:
        """
        提取 trace_id 和 request_id
        
        优先级：
        1. 从 event.tags 中提取（如果显式传递）
        2. 使用 LLM 从错误日志中智能提取
        3. 回退到正则匹配
        """
        # 优先级1：从 tags 中提取
        trace_id = None
        request_id = None
        if event.tags:
            trace_id = event.tags.get("trace_id") or event.tags.get("traceId") or event.tags.get("trace-id")
            request_id = event.tags.get("request_id") or event.tags.get("requestId") or event.tags.get("request-id")
            if trace_id:
                trace_id = str(trace_id)
            if request_id:
                request_id = str(request_id)
            if trace_id or request_id:
                logger.info(f"[LogEnricher] 从 tags 中提取到 trace_id={trace_id}, request_id={request_id}")
                return trace_id, request_id

        # 优先级2：使用 LLM 智能提取
        if self._llm is not None:
            logger.info("[LogEnricher] 🔍 使用 LLM 智能提取 trace_id/request_id")
            try:
                llm_result = await self._extract_trace_ids_with_llm(event.error_log)
                if llm_result:
                    trace_id = llm_result.get("trace_id") or trace_id
                    request_id = llm_result.get("request_id") or request_id
                    if trace_id or request_id:
                        logger.info(f"[LogEnricher] ✅ LLM 提取成功：trace_id={trace_id}, request_id={request_id}")
                        return trace_id, request_id
                    else:
                        logger.info("[LogEnricher] ⚠️ LLM 提取结果为空")
                else:
                    logger.info("[LogEnricher] ⚠️ LLM 提取返回 None")
            except Exception as e:
                logger.warning(f"[LogEnricher] ❌ LLM 提取失败，回退到正则匹配：{e}", exc_info=True)

        # 优先级3：正则匹配（回退方案）
        logger.info("[LogEnricher] 🔍 使用正则匹配提取 trace_id/request_id")
        trace_id_regex = self._extract_trace_id_regex(event.error_log)
        request_id_regex = self._extract_request_id_regex(event.error_log)
        
        if trace_id_regex or request_id_regex:
            logger.info(f"[LogEnricher] ✅ 正则匹配提取成功：trace_id={trace_id_regex}, request_id={request_id_regex}")
        else:
            logger.info("[LogEnricher] ⚠️ 正则匹配未提取到 trace_id/request_id")

        return trace_id_regex, request_id_regex

    async def _extract_trace_ids_with_llm(self, error_log: str) -> dict[str, str | None] | None:
        """
        使用 LLM 从错误日志中智能提取 trace_id 和 request_id
        
        Returns:
            {"trace_id": "...", "request_id": "..."} 或 None
        """
        if not self._llm:
            logger.debug("[LogEnricher] LLM 未配置，跳过 LLM 提取")
            return None

        # 截取错误日志的前 3000 字符（避免过长）
        log_preview = error_log[:3000]
        logger.debug(f"[LogEnricher] 准备使用 LLM 提取 trace_id，日志预览长度={len(log_preview)}")

        system = prompts.ENRICHER_TRACE_ID_SYSTEM_PROMPT
        user = prompts.ENRICHER_TRACE_ID_USER_PROMPT.format(log_preview=log_preview)

        try:
            logger.debug("[LogEnricher] 调用 LLM 提取 trace_id/request_id")
            raw = await self._llm.generate(system=system, user=user)
            logger.debug("[LogEnricher] trace_id 提取 AI 返回:\n%s", raw)
            
            # 尝试解析 JSON
            parsed = parse_json_markdown(raw)
            if isinstance(parsed, dict):
                result = {}
                trace_id = parsed.get("trace_id")
                request_id = parsed.get("request_id")
                if trace_id and trace_id.lower() != "null" and str(trace_id).strip():
                    result["trace_id"] = str(trace_id).strip()
                if request_id and request_id.lower() != "null" and str(request_id).strip():
                    result["request_id"] = str(request_id).strip()
                
                if result:
                    logger.info(f"[LogEnricher] LLM 解析成功：{result}")
                    return result
                else:
                    logger.debug("[LogEnricher] LLM 解析结果为空")
            else:
                logger.warning(f"[LogEnricher] LLM 返回结果无法解析为 JSON：{raw[:200]}")
        except Exception as e:
            logger.error(f"[LogEnricher] LLM 提取异常：{e}", exc_info=True)

        return None

    def _extract_trace_id_regex(self, error_log: str) -> str | None:
        """使用正则表达式提取 trace_id（回退方案）"""
        patterns = [
            r"trace_id[:=]\s*([a-zA-Z0-9_-]{16,})",
            r"traceId[:=]\s*([a-zA-Z0-9_-]{16,})",
            r"trace-id[:=]\s*([a-zA-Z0-9_-]{16,})",
            r"\[([a-zA-Z0-9_-]{32,})\]",  # 常见的 UUID 格式在方括号中
            r'"trace_id"\s*:\s*"([a-zA-Z0-9_-]{16,})"',  # JSON 格式
            r"'trace_id'\s*:\s*'([a-zA-Z0-9_-]{16,})'",  # JSON 格式（单引号）
        ]
        for pattern in patterns:
            match = re.search(pattern, error_log, re.IGNORECASE)
            if match:
                candidate = match.group(1)
                # 过滤掉明显不是 trace_id 的值（如 "null", "true", "false"）
                if candidate.lower() not in ("null", "true", "false", "none"):
                    return candidate
        return None

    def _extract_request_id_regex(self, error_log: str) -> str | None:
        """使用正则表达式提取 request_id（回退方案）"""
        patterns = [
            r"request_id[:=]\s*([a-zA-Z0-9_-]{16,})",
            r"requestId[:=]\s*([a-zA-Z0-9_-]{16,})",
            r"request-id[:=]\s*([a-zA-Z0-9_-]{16,})",
            r'"request_id"\s*:\s*"([a-zA-Z0-9_-]{16,})"',  # JSON 格式
            r"'request_id'\s*:\s*'([a-zA-Z0-9_-]{16,})'",  # JSON 格式（单引号）
        ]
        for pattern in patterns:
            match = re.search(pattern, error_log, re.IGNORECASE)
            if match:
                candidate = match.group(1)
                if candidate.lower() not in ("null", "true", "false", "none"):
                    return candidate
        return None

    async def _enrich_chain(
        self,
        event: NormalizedErrorEvent,
        trace_id: str | None,
        request_id: str | None,
    ) -> LogBundle:
        """
        查询调用链日志。
        
        使用 TraceChainProvider 接口，根据配置选择对应的实现：
        - 如果配置了 AliyunTraceChainProvider，使用阿里云 SLS 查询
        - 如果未配置，使用 EmptyTraceChainProvider（返回空列表）
        """
        if not self._trace_chain_provider:
            logger.debug("[LogEnricher] trace_chain_provider 未配置，返回空列表")
            return LogBundle(query_key="trace_chain", records=[], raw=None)
        
        # 计算时间范围（以事件时间为中心，前后扩展）
        # 限制最大时间窗口为5分钟（300秒）
        time_window = min(self._cfg.trace_chain_time_window_seconds, 300)
        start = event.timestamp - timedelta(seconds=time_window // 2)
        end = event.timestamp + timedelta(seconds=time_window // 2)
        logger.info(
            f"[LogEnricher] 调用链补充请求参数: trace_id={trace_id}, request_id={request_id}, "
            f"from_time={start.isoformat()}, to_time={end.isoformat()}"
        )
        # 调用 trace_chain_provider 查询
        return await self._trace_chain_provider.query_by_trace_id(
            trace_id=trace_id,
            request_id=request_id,
            from_time=start,
            to_time=end,
        )

    def _merge_bundles(self, base: LogBundle, chain: LogBundle) -> LogBundle:
        """合并两个 LogBundle，按时间排序"""
        from datetime import datetime, timezone

        all_records = list(base.records) + list(chain.records)
        # 按时间排序
        all_records.sort(
            key=lambda r: r.timestamp if r.timestamp else datetime.min.replace(tzinfo=timezone.utc)
        )
        return LogBundle(
            query_key=f"{base.query_key}+{chain.query_key}",
            records=all_records,
            raw={"base": base.raw, "chain": chain.raw},
        )
