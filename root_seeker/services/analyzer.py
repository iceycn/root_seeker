from __future__ import annotations

import json
import logging
import re
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable

from root_seeker.domain import (
    AnalysisReport,
    CandidateRepo,
    EvidencePack,
    LogBundle,
    LogRecord,
    NormalizedErrorEvent,
    ZoektHit,
)
from root_seeker.providers.llm import LLMProvider
from root_seeker.providers.notifiers import Notifier
from root_seeker.providers.zoekt import ZoektClient
from root_seeker.services.enricher import LogEnricher
from root_seeker.services.evidence import EvidenceBuilder
from root_seeker.services.router import ServiceRouter
from root_seeker.services.vector_retriever import VectorRetriever
from root_seeker.services.service_graph import ServiceGraph
from root_seeker.services.call_graph_expander import CallGraphExpander, CallGraphExpanderConfig
from root_seeker.services.conversation import ConversationHistory
from root_seeker.storage.analysis_store import AnalysisStore
from root_seeker import prompts
from root_seeker.utils import parse_json_markdown, redact_sensitive

logger = logging.getLogger(__name__)


def _normalize_business_impact(v: str | dict | None) -> str | None:
    """将 business_impact 规范化为字符串，如「高」「无：异常被捕获」"""
    if v is None:
        return None
    if isinstance(v, str) and v.strip():
        return v.strip()[:100]
    if isinstance(v, dict):
        level = v.get("level") or v.get("impact") or v.get("value")
        note = v.get("note") or v.get("reason")
        if level:
            s = str(level)
            if note:
                s += f"：{note}"
            return s[:100]
    return None


@dataclass(frozen=True)
class AnalyzerConfig:
    evidence_level: str = "L3"
    cross_repo_evidence: bool = False
    cross_repo_max_services: int = 2
    cross_repo_max_chunks_per_service: int = 3
    call_graph_expansion: bool = False
    call_graph_max_rounds: int = 2
    call_graph_max_methods_per_round: int = 5
    call_graph_max_total_methods: int = 15
    # 多轮对话配置（默认启用混合模式）
    llm_multi_turn_enabled: bool = True
    llm_multi_turn_mode: str = "hybrid"  # staged | self_refine | hybrid
    llm_multi_turn_max_rounds: int = 3
    llm_multi_turn_enable_self_review: bool = True
    llm_multi_turn_staged_round1: bool = True
    llm_multi_turn_staged_round2: bool = True
    llm_multi_turn_staged_round3: bool = True
    llm_multi_turn_self_refine_review_rounds: int = 1
    llm_multi_turn_self_refine_improvement_threshold: float = 0.1
    # 证据不足时补充检索：LLM 输出 NEED_MORE_EVIDENCE 时触发
    supplementary_evidence_enabled: bool = True
    supplementary_evidence_max_retries: int = 1
    # AI 驱动主流程：为 true 时优先使用 AiOrchestrator（Plan->Act->Synthesize），失败回退直连；默认 true 统一走 AI 驱动
    ai_driven_enabled: bool = True
    max_analysis_rounds: int = 20
    max_evidence_collection_depth: int = 20
    max_evidence_total_chars: int = 80_000
    # Hook 配置
    hooks_enabled: bool = True
    hooks_dirs: list[str] = field(default_factory=list)
    # 与 job_queue 超时对齐，避免 orchestrator 内部 300s 而 job 160s 导致不一致
    analysis_timeout_seconds: int = 160


class AnalyzerService:
    def __init__(
        self,
        *,
        cfg: AnalyzerConfig,
        router: ServiceRouter,
        enricher: LogEnricher,
        zoekt: ZoektClient | None,
        vector: VectorRetriever | None,
        graph_loader: Callable[[], ServiceGraph | None] | None,
        evidence_builder: EvidenceBuilder,
        llm: LLMProvider | None,
        notifiers: list[Notifier],
        store: AnalysisStore,
        mcp_gateway: Any | None = None,  # McpGateway
        audit: Any | None = None,  # AuditLogger
    ):
        self._cfg = cfg
        self._router = router
        self._enricher = enricher
        self._zoekt = zoekt
        self._vector = vector
        self._graph_loader = graph_loader
        self._evidence_builder = evidence_builder
        self._llm = llm
        self._notifiers = notifiers or []
        self._store = store
        self._mcp_gateway = mcp_gateway
        self._audit = audit

        # 方法级调用链展开器
        self._call_graph_expander = None
        if cfg.call_graph_expansion:
            from root_seeker.indexing.chunker import TreeSitterChunker

            tree_sitter_chunker = TreeSitterChunker()
            self._call_graph_expander = CallGraphExpander(
                cfg=CallGraphExpanderConfig(
                    enabled=cfg.call_graph_expansion,
                    max_rounds=cfg.call_graph_max_rounds,
                    max_methods_per_round=cfg.call_graph_max_methods_per_round,
                    max_total_methods=cfg.call_graph_max_total_methods,
                    use_tree_sitter=getattr(cfg, "call_graph_use_tree_sitter", True),
                    scan_limit_dirs=getattr(cfg, "call_graph_scan_limit_dirs", None),
                    cache_size=getattr(cfg, "call_graph_cache_size", 100),
                ),
                zoekt_client=zoekt,  # 异步 Zoekt 客户端
                tree_sitter_chunker=tree_sitter_chunker,
            )

    async def analyze(
        self,
        event: NormalizedErrorEvent,
        *,
        analysis_id: str | None = None,
        skip_ai_driven: bool = False,
        use_multi_turn_override: bool | None = None,
    ) -> AnalysisReport:
        """分析入口。ai_driven_enabled 时优先走 AiOrchestrator，失败回退直连。skip_ai_driven=True 时强制直连（供 analysis.run 等避免循环）。
        use_multi_turn_override：由 Plan 决定是否多轮对话，None 则用配置默认值。"""
        analysis_id = analysis_id or uuid.uuid4().hex
        cid = event.correlation_id or analysis_id
        logger.info(f"[Analyzer] 开始分析，analysis_id={analysis_id}, correlation_id={cid}, service={event.service_name}")

        use_ai_driven = (
            not skip_ai_driven
            and self._cfg.ai_driven_enabled
            and self._mcp_gateway is not None
            and self._llm is not None
        )
        if use_ai_driven:
            try:
                from root_seeker.ai.orchestrator import AiOrchestrator, OrchestratorConfig

                hook_hub = None
                if self._cfg.hooks_enabled:
                    from root_seeker.hooks.hub import HookHub
                    hook_hub = HookHub(
                        enabled=True,
                        hooks_dirs=self._cfg.hooks_dirs or [],
                    )
                orch = AiOrchestrator(
                    mcp_gateway=self._mcp_gateway,
                    llm=self._llm,
                    config=OrchestratorConfig(
                        max_tool_calls=8,
                        max_analysis_rounds=self._cfg.max_analysis_rounds,
                        max_evidence_collection_depth=self._cfg.max_evidence_collection_depth,
                        max_evidence_total_chars=self._cfg.max_evidence_total_chars,
                        llm_multi_turn_enabled=self._cfg.llm_multi_turn_enabled,
                        total_timeout_seconds=float(getattr(self._cfg, "analysis_timeout_seconds", 160)),
                    ),
                    audit=self._audit,
                    hook_hub=hook_hub,
                )
                report = await orch.analyze(event, analysis_id=analysis_id)
                self._store.save(report)
                await self._maybe_notify(report)
                logger.info(f"[Analyzer] AI 驱动分析完成，analysis_id={analysis_id}")
                return report
            except Exception as e:
                logger.warning(f"[Analyzer] AI 驱动分析失败，回退直连路径: {e}", exc_info=True)

        return await self._analyze_direct(event, analysis_id, use_multi_turn_override=use_multi_turn_override)

    async def _analyze_direct(
        self,
        event: NormalizedErrorEvent,
        analysis_id: str,
        *,
        use_multi_turn_override: bool | None = None,
    ) -> AnalysisReport:
        """直连分析路径：enrich -> zoekt -> vector -> evidence -> LLM。
        use_multi_turn_override：由 Plan 决定是否多轮，None 则用配置。"""
        candidates = self._router.route(event.service_name)
        if not candidates:
            # 兜底：从错误日志推断 service_name
            candidates = self._router.infer_from_error_log(event.error_log, event.service_name)
            if candidates:
                logger.info(f"[Analyzer] 从错误日志推断路由：{event.service_name} → {candidates[0].service_name}")
        if not candidates:
            logger.warning(f"[Analyzer] 未找到 service_name={event.service_name} 对应的仓库配置")
            report = AnalysisReport(
                analysis_id=analysis_id,
                service_name=event.service_name,
                summary="未找到该 service_name 对应的仓库配置或推断结果。",
                hypotheses=[],
                suggestions=["请先为该 service_name 配置仓库映射（git_url/local_dir）。"],
                correlation_id=event.correlation_id or analysis_id,
            )
            self._store.save(report)
            await self._maybe_notify(report)
            return report

        repo = candidates[0]
        logger.info(f"[Analyzer] 路由到仓库：{repo.service_name} -> {repo.local_dir}")
        
        logger.debug(f"[Analyzer] 开始日志补全，service={event.service_name}")
        log_bundle = await self._enricher.enrich(event)
        logger.info(f"[Analyzer] 日志补全完成，记录数={len(log_bundle.records)}")

        hits: list[ZoektHit] = []
        if self._zoekt is not None:
            query = self._build_zoekt_query(event, repo_name=repo.service_name)
            logger.info(f"[Analyzer] Zoekt 查询：{query}")
            try:
                raw_hits = await self._zoekt.search(query=query, max_matches=80)
                hits = self._filter_zoekt_hits_for_repo(raw_hits, repo.local_dir, event.service_name)
                hits = self._filter_and_sort_zoekt_hits(hits)
                hits = hits[:50]
                logger.info(f"[Analyzer] Zoekt 搜索完成，原始命中={len(raw_hits)}, 过滤后={len(hits)}")
                if len(raw_hits) == 0:
                    logger.warning(
                        f"[Analyzer] Zoekt 无命中，请检查：1) zoekt-webserver 是否已重启以加载新索引 "
                        f"2) 索引中 repo 名是否与 service_name={repo.service_name} 一致 3) 查询词是否在代码中存在"
                    )
            except Exception as e:
                logger.warning(f"[Analyzer] Zoekt 搜索失败：{e}", exc_info=True)
                hits = []
        else:
            logger.debug("[Analyzer] Zoekt 未配置，跳过代码搜索")

        vector_hits = None
        if self._vector is not None:
            logger.debug(f"[Analyzer] 开始向量检索，query={event.error_log[:200]}...")
            try:
                # 用 repo.service_name 过滤（索引时用的配置名），不用 event.service_name（可能为 K8s Pod 名）
                vector_hits = await self._vector.search(
                    query=event.error_log[:2000],
                    service_name=repo.service_name,
                    repo_local_dir=repo.local_dir,
                )
                logger.info(f"[Analyzer] 向量检索完成，命中数={len(vector_hits) if vector_hits else 0}")
            except Exception as e:
                logger.warning(f"[Analyzer] 向量检索失败：{e}", exc_info=True)
                vector_hits = None
        else:
            logger.debug("[Analyzer] 向量检索未配置，跳过")

        logger.debug(f"[Analyzer] 开始构建证据包，level={self._cfg.evidence_level}")
        evidence = self._evidence_builder.build(
            repo_local_dir=repo.local_dir,
            zoekt_hits=hits,
            vector_hits=vector_hits,
            level=self._cfg.evidence_level,
            error_log=event.error_log,
        )
        logger.info(f"[Analyzer] 证据包构建完成，文件数={len(evidence.files)}, 总字符数={sum(len(f.content) for f in evidence.files)}")

        # 方法级调用链展开：从代码片段解析方法调用关系并迭代扩展证据（异步）
        if self._call_graph_expander is not None:
            logger.debug("[Analyzer] 开始调用链展开")
            evidence = await self._call_graph_expander.expand_evidence(
                evidence=evidence,
                repo_local_dir=repo.local_dir,
                max_files=self._evidence_builder._limits.max_files,
                max_chars_total=self._evidence_builder._limits.max_chars_total,
                max_chars_per_file=self._evidence_builder._limits.max_chars_per_file,
            )
            logger.info(f"[Analyzer] 调用链展开完成，证据文件数={len(evidence.files)}")

        if (
            self._cfg.cross_repo_evidence
            and self._vector is not None
            and self._graph_loader is not None
        ):
            logger.debug("[Analyzer] 开始跨仓库证据收集")
            graph = self._graph_loader()
            if graph is not None:
                related: list = []
                related.extend(graph.upstream_of(event.service_name))
                related.extend(graph.downstream_of(event.service_name))
                logger.debug(f"[Analyzer] 关联服务：上游={len(graph.upstream_of(event.service_name))}, 下游={len(graph.downstream_of(event.service_name))}")
                for rel in related[: self._cfg.cross_repo_max_services]:
                    rel_name = getattr(rel, "service_name", None) or (rel if isinstance(rel, str) else None)
                    if not rel_name or rel_name == event.service_name:
                        continue
                    rel_candidates = self._router.route(rel_name)
                    if not rel_candidates:
                        continue
                    rel_repo = rel_candidates[0]
                    # 检查向量检索器是否可用
                    if self._vector is None:
                        logger.debug(f"[Analyzer] 向量检索器未配置，跳过跨仓库检索（{rel_name}）")
                        continue
                    try:
                        rel_hits = await self._vector.search(
                            query=event.error_log[:1500],
                            service_name=rel_name,
                            repo_local_dir=rel_repo.local_dir,
                        )
                    except Exception as e:
                        logger.debug(f"[Analyzer] 跨仓库向量检索失败（{rel_name}）：{e}")
                        rel_hits = []
                    if rel_hits:
                        self._evidence_builder.append_vector_hits_from_repo(
                            evidence,
                            repo_local_dir=rel_repo.local_dir,
                            vector_hits=rel_hits[: self._cfg.cross_repo_max_chunks_per_service],
                            max_add=self._cfg.cross_repo_max_chunks_per_service,
                            level=self._cfg.evidence_level,
                            service_name=rel_name,
                        )
                        logger.info(f"[Analyzer] 从关联服务 {rel_name} 追加了 {len(rel_hits[:self._cfg.cross_repo_max_chunks_per_service])} 条证据")

        multi_turn = use_multi_turn_override if use_multi_turn_override is not None else self._cfg.llm_multi_turn_enabled
        logger.info(
            f"[Analyzer] 开始生成分析报告，多轮对话={multi_turn} "
            f"({'Plan指定' if use_multi_turn_override is not None else '配置默认'})"
        )
        report = await self._generate_report(
            analysis_id=analysis_id,
            event=event,
            log_bundle=log_bundle,
            evidence=evidence,
            repo=repo,
            use_multi_turn_override=use_multi_turn_override,
        )
        if self._graph_loader is not None:
            graph = self._graph_loader()
            if graph is not None:
                related = []
                related.extend(graph.upstream_of(event.service_name))
                related.extend(graph.downstream_of(event.service_name))
                report = report.model_copy(update={"related_services": related})
                logger.debug(f"[Analyzer] 关联服务：{len(related)} 个")
        report = self._sanitize_report(report)
        self._store.save(report)
        logger.info(f"[Analyzer] 分析完成，analysis_id={analysis_id}, summary长度={len(report.summary)}, 假设数={len(report.hypotheses)}, 建议数={len(report.suggestions)}")
        await self._maybe_notify(report)
        return report

    async def synthesize_from_evidence(
        self,
        event: NormalizedErrorEvent,
        analysis_id: str,
        pre_collected_evidence: str,
        *,
        use_multi_turn: bool | None = None,
    ) -> AnalysisReport:
        """仅做 LLM 分析，接收 AI 通过工具自主收集的证据，不做 enrich/zoekt/vector。
        供 analysis.synthesize 工具使用，证据完全由 AI 驱动（Plan→Act）自主收集。"""
        if self._llm is None:
            return AnalysisReport(
                analysis_id=analysis_id,
                service_name=event.service_name,
                created_at=datetime.now(tz=timezone.utc),
                summary="未配置 LLM，无法生成报告。",
                hypotheses=[],
                suggestions=["配置 llm 后可生成分析报告。"],
                correlation_id=event.correlation_id or analysis_id,
            )
        log_bundle = LogBundle(
            query_key=event.query_key,
            records=[LogRecord(message=event.error_log[:2000])] if event.error_log else [],
        )
        evidence = EvidencePack(level=self._cfg.evidence_level, files=[], notes=[pre_collected_evidence])
        repo = None
        candidates = self._router.route(event.service_name)
        if candidates:
            repo = candidates[0]
        if repo is None:
            repo = CandidateRepo(service_name=event.service_name, local_dir="", git_url="")
        report = await self._generate_report(
            analysis_id=analysis_id,
            event=event,
            log_bundle=log_bundle,
            evidence=evidence,
            repo=repo,
            use_multi_turn_override=use_multi_turn,
        )
        report = self._sanitize_report(report)
        self._store.save(report)
        await self._maybe_notify(report)
        logger.info(f"[Analyzer] synthesize_from_evidence 完成，analysis_id={analysis_id}")
        return report

    async def _maybe_notify(self, report: AnalysisReport) -> None:
        if not self._notifiers:
            return
        markdown = self._to_markdown(report)
        title = f"错误分析：{report.service_name}"
        for n in self._notifiers:
            try:
                await n.send_markdown(title=title, markdown=markdown)
            except Exception:
                pass

    def _to_markdown(self, report: AnalysisReport) -> str:
        lines: list[str] = []
        lines.append(f"- analysis_id: {report.analysis_id}")
        lines.append(f"- 时间: {report.created_at.astimezone(timezone.utc).isoformat()}")
        if report.business_impact:
            lines.append(f"- 业务影响: {report.business_impact}")
        lines.append("")
        lines.append("**摘要**")
        lines.append(report.summary)
        if report.hypotheses:
            lines.append("")
            lines.append("**可能原因**")
            for h in report.hypotheses[:8]:
                lines.append(f"- {h}")
        if report.suggestions:
            lines.append("")
            lines.append("**修改建议**")
            for s in report.suggestions[:10]:
                lines.append(f"- {s}")
        if report.evidence and report.evidence.files:
            lines.append("")
            lines.append("**关键证据**")
            for ef in report.evidence.files[:6]:
                loc = ef.file_path
                if ef.start_line and ef.end_line:
                    loc = f"{loc}:{ef.start_line}-{ef.end_line}"
                lines.append(f"- {loc}（{ef.source}）")
        return "\n".join(lines)

    def _build_zoekt_query(self, event: NormalizedErrorEvent, repo_name: str | None = None) -> str:
        """
        构建 Zoekt 查询字符串。

        Zoekt 默认将空格连接的词按 AND 处理，多词会要求同时匹配导致 0 命中。
        因此将多个内容词用 or 连接，匹配任一即可。
        """
        repo_part = f"repo:{repo_name} " if repo_name else ""
        tokens = self._extract_stack_tokens(event.error_log)
        fallback = repo_name or event.service_name
        if not tokens:
            tokens = [fallback]
        # 限制词数，并用 or 连接（Zoekt 多词 AND 会过严导致 0 命中）
        content_tokens = tokens[:6]
        if len(content_tokens) == 1:
            content_part = content_tokens[0]
        else:
            content_part = "(" + " or ".join(content_tokens) + ")"
        q = (repo_part + content_part).strip()
        return q or fallback

    def _extract_stack_tokens(self, text: str) -> list[str]:
        tokens: list[str] = []
        for m in re.finditer(r"([A-Za-z0-9_./-]+\.(py|java))", text):
            tokens.append(m.group(1))
        for m in re.finditer(r"\b([A-Za-z_][A-Za-z0-9_]{2,})Exception\b", text):
            tokens.append(m.group(0))
        for m in re.finditer(r"\b(com\.[a-zA-Z0-9_.]+)\b", text):
            tokens.append(m.group(1))
        # Java 类名（含缩写包路径如 n.c.t.b.s.i.ClassName，取最后一段）
        for m in re.finditer(r"(?:^|[.\s])([A-Z][a-zA-Z0-9]*(?:Service|ServiceImpl|Biz|Controller|Template|Integration)(?:Impl)?)\b", text):
            tokens.append(m.group(1))
        # 缩写包路径后的类名：n.c.t.b.http.HttpRestTemplateService
        for m in re.finditer(r"[a-z]\.[a-z]\.[a-z]\.[a-z][a-z.]*\.([A-Z][a-zA-Z0-9]+)", text):
            tokens.append(m.group(1))
        # error_code / error_msg 中的关键标识（含下划线格式如 invalid_order_item_id）
        for m in re.finditer(r'"error_code"\s*:\s*"([^"]+)"', text):
            tokens.append(m.group(1))
        for m in re.finditer(r'"error_msg"\s*:\s*"([^"]+)"', text):
            # 从 error_msg 提取参数名等（如 "Invalid parameter order_item_id" -> order_item_id）
            msg = m.group(1)
            for subm in re.finditer(r"\b([a-z_][a-z0-9_]*)\b", msg):
                if len(subm.group(1)) >= 3 and subm.group(1) not in ("invalid", "parameter", "missing", "required"):
                    tokens.append(subm.group(1))
        # 方法名（getXxx、exchange 等，从日志上下文中提取）
        for m in re.finditer(r"\b(get[A-Z][a-zA-Z0-9]*|exchange|call[A-Z][a-zA-Z0-9]*)\b", text):
            tokens.append(m.group(1))
        # 当错误涉及 startTime 等 API 参数时，补充 Request 类名以便 Zoekt 召回类定义
        if re.search(r"startTime|填写正确|pointCharging|point.?charging", text, re.I):
            tokens.extend(["PointChargingRequest", "PointValueAddRequest"])
        return list(dict.fromkeys(tokens))

    def _filter_zoekt_hits_for_repo(
        self, hits: list[ZoektHit], repo_local_dir: str, service_name: str
    ) -> list[ZoektHit]:
        """只保留属于当前仓库的 Zoekt 命中，避免用其他仓库的 file_path 去当前 local_dir 下读文件。"""
        if not hits:
            return []
        repo_name = Path(repo_local_dir).name
        out: list[ZoektHit] = []
        for h in hits:
            r = h.repo
            if r is None or not str(r).strip():
                out.append(h)
                continue
            r = str(r).strip().rstrip("/")
            if (
                service_name == r
                or repo_name == r
                or repo_local_dir.rstrip("/").endswith(r)
                or r in repo_local_dir
            ):
                out.append(h)
        return out if out else hits

    def _filter_and_sort_zoekt_hits(self, hits: list[ZoektHit]) -> list[ZoektHit]:
        """排除无效路径（如 Windows 绝对路径、Maven 缓存），优先 .java/.py 源文件。"""
        if not hits:
            return []
        # 排除 Windows 绝对路径（索引可能来自 Windows 环境，本地为 Mac/Linux）
        _WINDOWS_ABSOLUTE = re.compile(r"^[A-Za-z]:[\\/]")
        valid: list[ZoektHit] = []
        for h in hits:
            fp = (h.file_path or "").replace("\\", "/")
            if _WINDOWS_ABSOLUTE.search(fp):
                continue
            valid.append(h)
        # 优先源文件：.java、.py 排前面，其次 src/ 下的文件
        def _score(h: ZoektHit) -> tuple[int, str]:
            fp = (h.file_path or "").lower()
            if fp.endswith(".java"):
                return (0, fp)
            if fp.endswith(".py"):
                return (1, fp)
            if "/src/" in fp or "\\src\\" in fp:
                return (2, fp)
            return (3, fp)

        valid.sort(key=_score)
        return valid

    # 补充检索时排除的泛化词（在代码中过于常见，用 or 连接会导致大量无关命中）
    _SUPPLEMENTARY_STOP_WORDS = frozenset({
        "error", "errors", "api", "null", "void", "get", "set", "log", "logs",
        "impl", "service", "biz", "third", "course", "timeout", "retry",
        "config", "request", "response", "data", "info", "debug", "warn",
        "test", "main", "run", "call", "method", "class", "type",
    })

    def _sanitize_supplementary_terms(self, query_terms: list[str]) -> list[str]:
        """
        清洗 NEED_MORE_EVIDENCE 检索词：优先保留类名、方法名等具体标识符，排除泛化词。
        泛化词（ERROR、API 等）用 or 连接会导致大量无关命中。
        """
        specific: list[str] = []  # 含 . 的 ClassName.methodName，最精准
        camel: list[str] = []    # CamelCase 类名
        other: list[str] = []    # 其他标识符
        seen: set[str] = set()

        def _add(s: str, *, allow_generic: bool = False) -> None:
            if not s or s in seen:
                return
            low = s.lower()
            if low in self._SUPPLEMENTARY_STOP_WORDS and not allow_generic:
                return
            if len(s) < 3:
                return
            seen.add(s)
            if "." in s:
                specific.append(s)
            elif re.match(r"^[A-Z][a-zA-Z0-9]*[a-z][A-Za-z0-9]*$", s):  # CamelCase
                camel.append(s)
            else:
                other.append(s)

        for t in query_terms:
            if not isinstance(t, str) or not t.strip():
                continue
            t = t.strip()
            for m in re.finditer(r"[A-Za-z_][A-Za-z0-9_]*(?:\.[A-Za-z_][A-Za-z0-9_]*)?", t):
                _add(m.group(0))
            for m in re.finditer(r"\b[A-Za-z_][A-Za-z0-9_]{4,}\b", t):  # 至少 5 字符，减少泛化
                _add(m.group(0))

        # 优先具体标识符，最多 4 个，避免 or 过多导致结果过泛
        out = (specific + camel + other)[:4]
        return out

    async def _append_supplementary_evidence(
        self,
        *,
        evidence: EvidencePack,
        query_terms: list[str],
        repo: CandidateRepo,
        event: NormalizedErrorEvent,
        max_extra_files: int = 5,
    ) -> int:
        """
        根据 LLM 请求的检索词补充证据，追加到 evidence。返回追加的文件数。
        """
        if not query_terms or not self._zoekt:
            return 0
        raw_terms = [t.strip() for t in query_terms if isinstance(t, str) and t.strip()][:6]
        if not raw_terms:
            return 0
        terms = self._sanitize_supplementary_terms(raw_terms)
        if not terms:
            terms = raw_terms[:4]  # 清洗后为空则回退到原始词（截断）
        content_part = "(" + " or ".join(terms) + ")" if len(terms) > 1 else terms[0]
        # 尝试多种 repo 名：service_name 与 local_dir 的 basename（Zoekt 索引可能用其一）
        repo_names = list(dict.fromkeys([repo.service_name, Path(repo.local_dir).name]))
        hits: list[ZoektHit] = []
        for rn in repo_names:
            if not rn:
                continue
            query = f"repo:{rn} {content_part}"
            logger.info(f"[Analyzer] 补充检索：{query} (原始词={raw_terms[:3]}...)")
            try:
                raw_hits = await self._zoekt.search(query=query, max_matches=20)
                hits = self._filter_zoekt_hits_for_repo(raw_hits, repo.local_dir, event.service_name)
                hits = self._filter_and_sort_zoekt_hits(hits)
                if hits:
                    break
            except Exception as e:
                logger.warning(f"[Analyzer] 补充 Zoekt 检索失败：{e}", exc_info=True)
        if not hits:
            return 0
        supp_pack = self._evidence_builder.build_from_zoekt_hits(
            repo_local_dir=repo.local_dir, hits=hits, level=self._cfg.evidence_level
        )
        seen_paths = {(f.file_path, f.start_line) for f in evidence.files}
        added = 0
        total_chars = sum(len(f.content) for f in evidence.files)
        for ef in supp_pack.files:
            if added >= max_extra_files or len(evidence.files) >= self._evidence_builder._limits.max_files:
                break
            key = (ef.file_path, ef.start_line)
            if key in seen_paths:
                continue
            if total_chars + len(ef.content) > self._evidence_builder._limits.max_chars_total:
                break
            seen_paths.add(key)
            evidence.files.append(ef.model_copy(update={"source": "zoekt_supplementary"}))
            total_chars += len(ef.content)
            added += 1
        if self._vector and added < max_extra_files:
            try:
                vector_query = " ".join(terms)[:1500]
                vhits = await self._vector.search(
                    query=vector_query,
                    service_name=repo.service_name,
                    repo_local_dir=repo.local_dir,
                )
                self._evidence_builder.append_vector_hits_from_repo(
                    evidence,
                    repo_local_dir=repo.local_dir,
                    vector_hits=vhits[:3],
                    max_add=min(3, max_extra_files - added),
                    level=self._cfg.evidence_level,
                    service_name=repo.service_name,
                )
            except Exception as e:
                logger.debug(f"[Analyzer] 补充向量检索失败：{e}")
        if raw_terms:
            evidence.notes.append(
                prompts.ANALYZER_SUPPLEMENTARY_EVIDENCE_PROMPT.format(
                    need_terms=raw_terms, added=added, terms=terms
                )
            )
        return added

    def _extract_need_more_evidence(self, result: dict | None) -> list[str]:
        """从 LLM 输出中提取 NEED_MORE_EVIDENCE 字段"""
        if not isinstance(result, dict):
            return []
        raw = result.get("NEED_MORE_EVIDENCE") or result.get("need_more_evidence")
        if isinstance(raw, list):
            return [str(x) for x in raw if x]
        if isinstance(raw, str) and raw.strip():
            return [raw.strip()]
        return []

    async def _generate_report(
        self,
        *,
        analysis_id: str,
        event: NormalizedErrorEvent,
        log_bundle: LogBundle,
        evidence: EvidencePack,
        repo: CandidateRepo,
        use_multi_turn_override: bool | None = None,
    ) -> AnalysisReport:
        if self._llm is None:
            return AnalysisReport(
                analysis_id=analysis_id,
                service_name=event.service_name,
                created_at=datetime.now(tz=timezone.utc),
                summary="未配置云端LLM，已完成检索与证据收集。",
                hypotheses=[],
                suggestions=["配置 llm.base_url/api_key/model 后可生成原因与修复建议。"],
                evidence=evidence,
                correlation_id=event.correlation_id or analysis_id,
            )

        # Plan 可指定是否多轮；未指定则用配置
        use_multi = use_multi_turn_override if use_multi_turn_override is not None else self._cfg.llm_multi_turn_enabled
        if use_multi:
            return await self._generate_report_multi_turn(
                analysis_id=analysis_id,
                event=event,
                log_bundle=log_bundle,
                evidence=evidence,
                repo=repo,
            )
        else:
            return await self._generate_report_single_turn(
                analysis_id=analysis_id,
                event=event,
                log_bundle=log_bundle,
                evidence=evidence,
            )

    async def _generate_report_single_turn(
        self,
        *,
        analysis_id: str,
        event: NormalizedErrorEvent,
        log_bundle: LogBundle,
        evidence: EvidencePack,
    ) -> AnalysisReport:
        """单轮对话模式（原有逻辑）"""
        system = prompts.ANALYZER_SYSTEM_PROMPT
        user = self._build_llm_user_prompt(event=event, log_bundle=log_bundle, evidence=evidence)
        raw = await self._llm.generate(system=system, user=user)
        logger.debug("[Analyzer] 单轮分析 AI 返回:\n%s", raw)
        parsed = parse_json_markdown(raw)
        summary_raw = parsed.get("summary") if isinstance(parsed, dict) else None
        # 处理 summary 可能是字典的情况（如 {"direct_cause": "...", "phenomenon": "..."}）
        if isinstance(summary_raw, dict):
            # 尝试提取字典中的常见字段（包括 phenomenon）
            summary = (
                summary_raw.get("direct_cause") 
                or summary_raw.get("summary") 
                or summary_raw.get("description") 
                or summary_raw.get("phenomenon")
                or ""
            )
            if not summary:
                # 如果都没有，将字典转换为可读文本
                summary = ", ".join(f"{k}: {v}" for k, v in summary_raw.items() if v)
        else:
            summary = str(summary_raw or "") if summary_raw is not None else ""
        hypotheses = parsed.get("hypotheses") if isinstance(parsed, dict) else None
        suggestions = parsed.get("suggestions") if isinstance(parsed, dict) else None
        business_impact = _normalize_business_impact(parsed.get("business_impact") if isinstance(parsed, dict) else None)
        need_more = parsed.get("NEED_MORE_EVIDENCE") or parsed.get("need_more_evidence") if isinstance(parsed, dict) else None
        need_more_evidence = [str(x).strip() for x in need_more if str(x).strip()][:6] if isinstance(need_more, list) else None
        if not summary:
            summary = "模型未返回summary字段，已保留原始输出。"
        # 确保 summary 是字符串类型（防御性编程）
        if not isinstance(summary, str):
            logger.warning(f"[Analyzer] single_turn summary 不是字符串类型：{type(summary)}, 值={summary}")
            if isinstance(summary, dict):
                summary = ", ".join(f"{k}: {v}" for k, v in summary.items() if v) or "模型未返回summary字段，已保留原始输出。"
            else:
                summary = str(summary) if summary else "模型未返回summary字段，已保留原始输出。"
        return AnalysisReport(
            analysis_id=analysis_id,
            service_name=event.service_name,
            created_at=datetime.now(tz=timezone.utc),
            summary=summary,
            hypotheses=[str(x) for x in (hypotheses or [])][:12],
            suggestions=[str(x) for x in (suggestions or [])][:16],
            evidence=evidence,
            raw_model_output=raw,
            business_impact=business_impact,
            correlation_id=event.correlation_id or analysis_id,
            need_more_evidence=need_more_evidence,
        )

    async def _generate_report_multi_turn(
        self,
        *,
        analysis_id: str,
        event: NormalizedErrorEvent,
        log_bundle: LogBundle,
        evidence: EvidencePack,
        repo: CandidateRepo,
    ) -> AnalysisReport:
        """多轮对话模式：根据配置选择不同的模式"""
        mode = self._cfg.llm_multi_turn_mode
        if mode == "staged":
            return await self._generate_report_staged(
                analysis_id=analysis_id,
                event=event,
                log_bundle=log_bundle,
                evidence=evidence,
                repo=repo,
            )
        elif mode == "self_refine":
            return await self._generate_report_self_refine(
                analysis_id=analysis_id,
                event=event,
                log_bundle=log_bundle,
                evidence=evidence,
                repo=repo,
            )
        elif mode == "hybrid":
            return await self._generate_report_hybrid(
                analysis_id=analysis_id,
                event=event,
                log_bundle=log_bundle,
                evidence=evidence,
                repo=repo,
            )
        else:
            # 未知模式，降级到单轮
            return await self._generate_report_single_turn(
                analysis_id=analysis_id,
                event=event,
                log_bundle=log_bundle,
                evidence=evidence,
            )

    def _extract_error_code_msg(self, error_log: str) -> str:
        """从 error_log 提取常见错误信息（JSON 字段、异常类型等），供 AI 优先识别。"""
        if not error_log or not isinstance(error_log, str):
            return ""
        parts: list[str] = []
        seen: set[str] = set()

        def _add(label: str, val: str) -> None:
            key = f"{label}:{val}"
            if key not in seen and val.strip():
                seen.add(key)
                parts.append(f"【提取】{label}: {val.strip()[:500]}")

        # JSON 格式：error_code / errorCode / code（非数字）
        for m in re.finditer(r'"(?:error_code|errorCode)"\s*:\s*"([^"]+)"', error_log, re.I):
            _add("error_code", m.group(1))
        for m in re.finditer(r'"code"\s*:\s*"([^"]+)"', error_log):
            v = m.group(1)
            if not v.isdigit() and len(v) > 1:
                _add("code", v)
        # error_msg / errorMsg / message / msg
        for m in re.finditer(r'"(?:error_msg|errorMsg|message|msg)"\s*:\s*"([^"]+)"', error_log, re.I):
            _add("message", m.group(1))
        # detail / reason / description
        for m in re.finditer(r'"(?:detail|reason|description)"\s*:\s*"([^"]+)"', error_log, re.I):
            _add("detail", m.group(1))
        # resp= 或 response= 内嵌 JSON
        for m in re.finditer(r'(?:resp|response)\s*=\s*\{[^}]*"(?:error_code|error_msg|message|code)"\s*:\s*"([^"]+)"', error_log, re.I):
            _add("resp", m.group(1))
        # 异常类型（Java/Python）
        for m in re.finditer(r'\b([A-Za-z0-9_]+(?:Exception|Error))(?:\s|:|$)', error_log):
            _add("exception", m.group(1))
        # Caused by: xxx
        for m in re.finditer(r'(?:Caused by|cause):\s*([A-Za-z0-9_.]+)\s*:\s*([^\n]+)', error_log, re.I):
            _add("caused_by", f"{m.group(1)}: {m.group(2)[:200]}")
        if parts:
            return "【重要】日志中已识别到的错误信息（请优先分析）：\n" + "\n".join(parts) + "\n\n"
        return ""

    def _build_llm_user_prompt(
        self, *, event: NormalizedErrorEvent, log_bundle: LogBundle, evidence: EvidencePack
    ) -> str:
        logs_preview = self._truncate_logs_for_llm(log_bundle, max_records=80, max_total_chars=15_000)
        evidence_preview = self._format_evidence_for_llm(evidence)
        extracted_error_info = self._extract_error_code_msg(event.error_log or "")
        schema = {
            "summary": "一句话到三句话，总结定位结论",
            "hypotheses": ["可能原因1", "可能原因2"],
            "suggestions": ["建议修改1", "建议修改2"],
            "business_impact": "高|中|低|无，可附带说明如「无：异常被捕获不影响主流程」",
            "NEED_MORE_EVIDENCE": "若证据不足、无法确定根因，填写建议补充检索的关键词数组，否则省略",
        }
        return prompts.ANALYZER_SINGLE_TURN_USER_PROMPT.format(
            service_name=event.service_name,
            extracted_error_info=extracted_error_info,
            error_log=event.error_log,
            logs_preview=logs_preview,
            evidence_preview=evidence_preview,
            schema_example=json.dumps(schema, ensure_ascii=False)
        )

    def _sanitize_report(self, report: AnalysisReport) -> AnalysisReport:
        """脱敏：输出前移除 AK/SK、token、连接串等敏感信息。"""
        return report.model_copy(
            update={
                "summary": redact_sensitive(report.summary),
                "hypotheses": [redact_sensitive(str(h)) for h in (report.hypotheses or [])],
                "suggestions": [redact_sensitive(str(s)) for s in (report.suggestions or [])],
                "business_impact": redact_sensitive(report.business_impact) if report.business_impact else None,
            }
        )

    def _truncate_logs_for_llm(
        self, log_bundle: LogBundle, max_records: int = 80, max_total_chars: int = 15_000
    ) -> str:
        """大日志截断：限制记录数与总字符数，防止 LLM 上下文爆炸。"""
        lines: list[str] = []
        total = 0
        for r in log_bundle.records[:max_records]:
            msg = (r.message or "")[:500]
            if total + len(msg) + 1 > max_total_chars:
                lines.append(f"...[已截断，共 {len(log_bundle.records)} 条]")
                break
            lines.append(msg)
            total += len(msg) + 1
        return "\n".join(lines)

    def _format_evidence_for_llm(self, evidence: EvidencePack) -> str:
        out: list[str] = []
        for ef in evidence.files:
            header = f"--- {ef.file_path}:{ef.start_line}-{ef.end_line} ({ef.source}) ---"
            out.append(header)
            out.append(ef.content)
        if evidence.notes:
            out.append("--- notes ---")
            out.extend(evidence.notes)
        return "\n".join(out)

    async def _generate_report_staged(
        self,
        *,
        analysis_id: str,
        event: NormalizedErrorEvent,
        log_bundle: LogBundle,
        evidence: EvidencePack,
        repo: CandidateRepo,
    ) -> AnalysisReport:
        """
        方案A：分阶段多轮分析
        阶段1：快速定位
        阶段2：深入分析
        阶段3：生成建议
        """
        system = prompts.ANALYZER_SYSTEM_PROMPT
        history = ConversationHistory()
        round1_result = None
        round2_result = None
        round3_result = None
        round1_raw = ""
        round2_raw = ""
        round3_raw = ""

        # Round 1: 快速定位
        if self._cfg.llm_multi_turn_staged_round1:
            round1_prompt = self._build_staged_round1_prompt(event=event)
            history.add_user_message(round1_prompt)
            round1_raw = await self._llm.generate_multi_turn(system=system, messages=history.messages)
            logger.debug("[Analyzer] 分阶段 Round1 快速定位 AI 返回:\n%s", round1_raw)
            history.add_assistant_message(round1_raw)
            round1_result = parse_json_markdown(round1_raw)

        # Round 2: 深入分析（支持证据不足时补充检索并重试）
        if self._cfg.llm_multi_turn_staged_round2:
            round2_retries = self._cfg.supplementary_evidence_max_retries if self._cfg.supplementary_evidence_enabled else 0
            for retry in range(round2_retries + 1):
                round2_prompt = self._build_staged_round2_prompt(
                    event=event, evidence=evidence, round1_result=round1_result
                )
                history.add_user_message(round2_prompt)
                round2_raw = await self._llm.generate_multi_turn(system=system, messages=history.messages)
                logger.debug("[Analyzer] 分阶段 Round2 深入分析 AI 返回:\n%s", round2_raw)
                history.add_assistant_message(round2_raw)
                round2_result = parse_json_markdown(round2_raw)
                need_terms = self._extract_need_more_evidence(round2_result)
                if not need_terms or retry >= round2_retries:
                    break
                added = await self._append_supplementary_evidence(
                    evidence=evidence,
                    query_terms=need_terms,
                    repo=repo,
                    event=event,
                )
                if added > 0:
                    history.add_user_message(
                        prompts.ANALYZER_SUPPLEMENTARY_EVIDENCE_PROMPT.format(
                            need_terms=need_terms, added=added
                        )
                    )
                else:
                    break

        # Round 3: 生成建议（失败时优雅降级，基于 Round 1/2 返回部分结果）
        round3_failed = False
        if self._cfg.llm_multi_turn_staged_round3:
            round3_prompt = self._build_staged_round3_prompt(
                event=event, log_bundle=log_bundle, round1_result=round1_result, round2_result=round2_result
            )
            history.add_user_message(round3_prompt)
            try:
                round3_raw = await self._llm.generate_multi_turn(system=system, messages=history.messages)
                logger.debug("[Analyzer] 分阶段 Round3 生成建议 AI 返回:\n%s", round3_raw)
                history.add_assistant_message(round3_raw)
                round3_result = parse_json_markdown(round3_raw)
            except Exception as e:
                logger.warning(f"[Analyzer] Round 3 生成建议失败（超时或网络错误），将基于前两轮结果返回部分报告：{e}")
                round3_raw = ""
                round3_result = {}
                round3_failed = True

        # 合并结果
        summary = self._merge_staged_summary(round1_result, round2_result, round3_result)
        if round3_failed and summary:
            summary = summary.rstrip("。") + "（Round 3 生成建议超时，已基于前两轮结果输出。）"
        # 确保 summary 是字符串类型（防御性编程）
        if not isinstance(summary, str):
            logger.warning(f"[Analyzer] _merge_staged_summary 返回了非字符串类型：{type(summary)}, 值={summary}")
            if isinstance(summary, dict):
                summary = ", ".join(f"{k}: {v}" for k, v in summary.items() if v) or "已完成分阶段分析，但未获取到有效摘要。"
            else:
                summary = str(summary) if summary else "已完成分阶段分析，但未获取到有效摘要。"
        hypotheses = self._merge_staged_hypotheses(round2_result)
        suggestions = self._merge_staged_suggestions(round3_result)
        if round3_failed and not suggestions and hypotheses:
            suggestions = ["建议根据上述根因分析，进一步排查具体代码实现。"]
        business_impact = _normalize_business_impact(
            round3_result.get("business_impact") if isinstance(round3_result, dict) else None
        )
        raw_output = "--- Round 1 (快速定位) ---\n" + (round1_raw if round1_raw else "")
        if round2_raw:
            raw_output += "\n\n--- Round 2 (深入分析) ---\n" + round2_raw
        if round3_raw:
            raw_output += "\n\n--- Round 3 (生成建议) ---\n" + round3_raw
        elif round3_failed:
            raw_output += "\n\n--- Round 3 (生成建议) ---\n[超时或网络错误，已降级返回部分结果]"

        return AnalysisReport(
            analysis_id=analysis_id,
            service_name=event.service_name,
            created_at=datetime.now(tz=timezone.utc),
            summary=summary,
            hypotheses=hypotheses[:12],
            suggestions=suggestions[:16],
            evidence=evidence,
            raw_model_output=raw_output,
            business_impact=business_impact,
            correlation_id=event.correlation_id or analysis_id,
        )

    async def _generate_report_self_refine(
        self,
        *,
        analysis_id: str,
        event: NormalizedErrorEvent,
        log_bundle: LogBundle,
        evidence: EvidencePack,
        repo: CandidateRepo,
    ) -> AnalysisReport:
        """
        方案B：Self-Refine 迭代优化
        Round 1: 初步分析
        Round 2-N: 自我审查和优化
        """
        system = prompts.ANALYZER_SYSTEM_PROMPT
        history = ConversationHistory()

        # Round 1: 初步分析（支持证据不足时补充检索并重试）
        round1_retries = self._cfg.supplementary_evidence_max_retries if self._cfg.supplementary_evidence_enabled else 0
        round1_result = None
        round1_raw = ""
        for retry in range(round1_retries + 1):
            round1_prompt = self._build_llm_user_prompt(event=event, log_bundle=log_bundle, evidence=evidence)
            history.add_user_message(round1_prompt)
            round1_raw = await self._llm.generate_multi_turn(system=system, messages=history.messages)
            logger.debug("[Analyzer] Self-Refine Round1 初步分析 AI 返回:\n%s", round1_raw)
            history.add_assistant_message(round1_raw)
            round1_result = parse_json_markdown(round1_raw)
            need_terms = self._extract_need_more_evidence(round1_result)
            if not need_terms or retry >= round1_retries:
                break
            added = await self._append_supplementary_evidence(
                evidence=evidence,
                query_terms=need_terms,
                repo=repo,
                event=event,
            )
            if added > 0:
                history.add_user_message(
                    prompts.ANALYZER_SUPPLEMENTARY_EVIDENCE_PROMPT.format(
                        need_terms=need_terms, added=added
                    )
                )
            else:
                break

        # Round 2-N: 自我审查和优化
        review_rounds = self._cfg.llm_multi_turn_self_refine_review_rounds
        last_result = round1_result
        raw_output = "--- Round 1 (初步分析) ---\n" + round1_raw

        for i in range(review_rounds):
            # 自我审查
            review_prompt = self._build_self_refine_review_prompt(last_result)
            history.add_user_message(review_prompt)
            review_raw = await self._llm.generate_multi_turn(system=system, messages=history.messages)
            logger.debug("[Analyzer] Self-Refine Round%d 审查 AI 返回:\n%s", i + 2, review_raw)
            history.add_assistant_message(review_raw)
            raw_output += f"\n\n--- Round {i+2} (审查) ---\n" + review_raw

            # 优化分析
            refine_prompt = self._build_self_refine_refine_prompt(
                event=event, log_bundle=log_bundle, evidence=evidence, last_result=last_result, review_feedback=review_raw
            )
            history.add_user_message(refine_prompt)
            refine_raw = await self._llm.generate_multi_turn(system=system, messages=history.messages)
            logger.debug("[Analyzer] Self-Refine Round%d 优化 AI 返回:\n%s", i + 2, refine_raw)
            history.add_assistant_message(refine_raw)
            refine_result = parse_json_markdown(refine_raw)
            raw_output += f"\n\n--- Round {i+2} (优化) ---\n" + refine_raw

            # 检查改进幅度（简化版：如果结果相同或相似，提前终止）
            if self._is_improvement_significant(last_result, refine_result):
                last_result = refine_result
            else:
                break

        # 使用最后的结果
        summary_raw = last_result.get("summary") if isinstance(last_result, dict) else None
        # 处理 summary 可能是字典的情况（如 {"direct_cause": "...", "phenomenon": "..."}）
        if isinstance(summary_raw, dict):
            # 尝试提取字典中的常见字段（包括 phenomenon）
            summary = (
                summary_raw.get("direct_cause") 
                or summary_raw.get("summary") 
                or summary_raw.get("description") 
                or summary_raw.get("phenomenon")
                or ""
            )
            if not summary:
                # 如果都没有，将字典转换为可读文本
                summary = ", ".join(f"{k}: {v}" for k, v in summary_raw.items() if v)
        else:
            summary = str(summary_raw or "") if summary_raw is not None else ""
        hypotheses = last_result.get("hypotheses") if isinstance(last_result, dict) else []
        suggestions = last_result.get("suggestions") if isinstance(last_result, dict) else []
        business_impact = _normalize_business_impact(last_result.get("business_impact") if isinstance(last_result, dict) else None)

        if not summary:
            summary = "模型未返回summary字段，已保留原始输出。"
        
        # 确保 summary 是字符串类型（防御性编程）
        if not isinstance(summary, str):
            logger.warning(f"[Analyzer] self_refine summary 不是字符串类型：{type(summary)}, 值={summary}")
            if isinstance(summary, dict):
                summary = ", ".join(f"{k}: {v}" for k, v in summary.items() if v) or "模型未返回summary字段，已保留原始输出。"
            else:
                summary = str(summary) if summary else "模型未返回summary字段，已保留原始输出。"

        return AnalysisReport(
            analysis_id=analysis_id,
            service_name=event.service_name,
            created_at=datetime.now(tz=timezone.utc),
            summary=summary,
            hypotheses=[str(x) for x in hypotheses][:12],
            suggestions=[str(x) for x in suggestions][:16],
            evidence=evidence,
            raw_model_output=raw_output,
            business_impact=business_impact,
            correlation_id=event.correlation_id or analysis_id,
        )

    async def _generate_report_hybrid(
        self,
        *,
        analysis_id: str,
        event: NormalizedErrorEvent,
        log_bundle: LogBundle,
        evidence: EvidencePack,
        repo: CandidateRepo,
    ) -> AnalysisReport:
        """
        方案C：混合模式
        先执行分阶段分析，然后可选地执行自我审查和优化
        """
        # 先执行分阶段分析
        staged_report = await self._generate_report_staged(
            analysis_id=analysis_id,
            event=event,
            log_bundle=log_bundle,
            evidence=evidence,
            repo=repo,
        )

        # 如果启用自我审查，进行优化（失败时直接返回分阶段结果）
        if self._cfg.llm_multi_turn_enable_self_review:
            try:
                return await self._do_hybrid_self_review(
                    analysis_id=analysis_id,
                    event=event,
                    staged_report=staged_report,
                )
            except Exception as e:
                logger.warning(f"[Analyzer] Hybrid 自我审查失败，返回分阶段结果：{e}")
        return staged_report

    async def _do_hybrid_self_review(
        self,
        *,
        analysis_id: str,
        event: NormalizedErrorEvent,
        staged_report: AnalysisReport,
    ) -> AnalysisReport:
        """执行 Hybrid 模式的自我审查与优化"""
        system = prompts.ANALYZER_SYSTEM_PROMPT
        history = ConversationHistory()

        # 添加分阶段分析的结果作为上下文
        history.add_user_message(
            prompts.ANALYZER_HYBRID_REVIEW_USER_PROMPT.format(
                summary=staged_report.summary,
                hypotheses=staged_report.hypotheses,
                suggestions=staged_report.suggestions,
                business_impact=staged_report.business_impact or '未评估'
            )
        )
        review_raw = await self._llm.generate_multi_turn(system=system, messages=history.messages)
        logger.debug("[Analyzer] Hybrid 审查 AI 返回:\n%s", review_raw)
        history.add_assistant_message(review_raw)

        # 基于审查结果优化
        refine_prompt = prompts.ANALYZER_HYBRID_REFINE_USER_PROMPT.format(
            review_feedback=review_raw,
            error_log=event.error_log
        )
        history.add_user_message(refine_prompt)
        refine_raw = await self._llm.generate_multi_turn(system=system, messages=history.messages)
        logger.debug("[Analyzer] Hybrid 优化 AI 返回:\n%s", refine_raw)
        refine_result = parse_json_markdown(refine_raw)

        # 合并优化结果
        if isinstance(refine_result, dict):
                summary_raw = refine_result.get("summary")
                # 处理 summary 可能是字典的情况（包括 phenomenon）
                if isinstance(summary_raw, dict):
                    summary = (
                        summary_raw.get("direct_cause") 
                        or summary_raw.get("summary") 
                        or summary_raw.get("description") 
                        or summary_raw.get("phenomenon")
                        or ""
                    )
                    if not summary:
                        # 如果都没有，将字典转换为可读文本
                        summary = ", ".join(f"{k}: {v}" for k, v in summary_raw.items() if v)
                else:
                    summary = str(summary_raw or "") if summary_raw is not None else ""
                if not summary:
                    summary = staged_report.summary
                hypotheses = refine_result.get("hypotheses") or staged_report.hypotheses
                suggestions = refine_result.get("suggestions") or staged_report.suggestions
                business_impact = _normalize_business_impact(refine_result.get("business_impact")) or staged_report.business_impact
        else:
            summary = staged_report.summary
            hypotheses = staged_report.hypotheses
            suggestions = staged_report.suggestions
            business_impact = staged_report.business_impact

        # 确保 summary 是字符串类型（防御性编程）
        if not isinstance(summary, str):
            logger.warning(f"[Analyzer] hybrid summary 不是字符串类型：{type(summary)}, 值={summary}")
            if isinstance(summary, dict):
                summary = ", ".join(f"{k}: {v}" for k, v in summary.items() if v) or (staged_report.summary if hasattr(staged_report, 'summary') else "已完成分析，但未获取到有效摘要。")
            else:
                summary = str(summary) if summary else (staged_report.summary if hasattr(staged_report, 'summary') else "已完成分析，但未获取到有效摘要。")

        return AnalysisReport(
            analysis_id=analysis_id,
            service_name=event.service_name,
            created_at=datetime.now(tz=timezone.utc),
            summary=summary,
            hypotheses=[str(x) for x in hypotheses][:12],
            suggestions=[str(x) for x in suggestions][:16],
            evidence=staged_report.evidence,
            raw_model_output=staged_report.raw_model_output + "\n\n--- 审查与优化 ---\n" + review_raw + "\n" + refine_raw,
            business_impact=business_impact,
            correlation_id=event.correlation_id or analysis_id,
        )

    def _build_staged_round1_prompt(self, *, event: NormalizedErrorEvent) -> str:
        """构建阶段1：快速定位的 prompt"""
        schema = {
            "problem_location": "文件路径:行号（从堆栈中提取）",
            "error_type": "异常类型",
            "quick_summary": "一句话总结问题",
        }
        extracted = self._extract_error_code_msg(event.error_log or "")
        return prompts.ANALYZER_STAGED_ROUND1_PROMPT.format(
            extracted_error_info=extracted,
            error_log=event.error_log,
            schema_example=json.dumps(schema, ensure_ascii=False)
        )

    def _build_staged_round2_prompt(
        self, *, event: NormalizedErrorEvent, evidence: EvidencePack, round1_result: dict | None
    ) -> str:
        """构建阶段2：深入分析的 prompt"""
        round1_text = ""
        if round1_result:
            round1_text = f"第一轮定位结果：\n{json.dumps(round1_result, ensure_ascii=False)}\n\n"

        evidence_preview = self._format_evidence_for_llm(evidence)
        schema = {
            "root_cause": "根本原因分析（2-3句话）",
            "hypotheses": ["可能原因1", "可能原因2", "可能原因3"],
            "evidence_analysis": "关键证据分析（说明哪些代码片段支持上述假设）",
            "NEED_MORE_EVIDENCE": "若证据不足、无法确定根因，填写建议补充检索的关键词数组（如类名、方法名、配置项），否则省略",
        }
        return prompts.ANALYZER_STAGED_ROUND2_PROMPT.format(
            round1_text=round1_text,
            evidence_preview=evidence_preview,
            schema_example=json.dumps(schema, ensure_ascii=False)
        )

    def _build_staged_round3_prompt(
        self,
        *,
        event: NormalizedErrorEvent,
        log_bundle: LogBundle,
        round1_result: dict | None,
        round2_result: dict | None,
    ) -> str:
        """构建阶段3：生成建议的 prompt"""
        round1_text = ""
        if round1_result:
            round1_text = f"定位结果：\n{json.dumps(round1_result, ensure_ascii=False)}\n\n"

        round2_text = ""
        if round2_result:
            round2_text = f"原因分析：\n{json.dumps(round2_result, ensure_ascii=False)}\n\n"

        logs_preview = self._truncate_logs_for_llm(log_bundle, max_records=40, max_total_chars=8_000)
        schema = {
            "suggestions": ["建议1（具体可操作）", "建议2", "建议3"],
            "priority": "高/中/低",
            "business_impact": "高|中|低|无，可附带说明如「无：异常被捕获不影响主流程」",
            "implementation_hints": "实现提示（可选）",
        }
        return prompts.ANALYZER_STAGED_ROUND3_PROMPT.format(
            round1_text=round1_text,
            round2_text=round2_text,
            logs_preview=logs_preview,
            schema_example=json.dumps(schema, ensure_ascii=False)
        )

    def _build_self_refine_review_prompt(self, last_result: dict | None) -> str:
        """构建 Self-Refine 审查 prompt"""
        result_text = json.dumps(last_result, ensure_ascii=False) if last_result else "无"
        schema = {
            "review_feedback": ["反馈1", "反馈2"],
            "needs_improvement": ["需要改进的地方1", "需要改进的地方2"],
        }
        return prompts.ANALYZER_SELF_REFINE_REVIEW_PROMPT.format(
            result_text=result_text,
            schema_example=json.dumps(schema, ensure_ascii=False)
        )

    def _build_self_refine_refine_prompt(
        self,
        *,
        event: NormalizedErrorEvent,
        log_bundle: LogBundle,
        evidence: EvidencePack,
        last_result: dict | None,
        review_feedback: str,
    ) -> str:
        """构建 Self-Refine 优化 prompt"""
        logs_preview = self._truncate_logs_for_llm(log_bundle, max_records=80, max_total_chars=15_000)
        evidence_preview = self._format_evidence_for_llm(evidence)
        last_result_text = json.dumps(last_result, ensure_ascii=False) if last_result else "无"

        schema = {
            "summary": "一句话到三句话，总结定位结论",
            "hypotheses": ["可能原因1", "可能原因2"],
            "suggestions": ["建议修改1", "建议修改2"],
            "business_impact": "高|中|低|无，可附带说明如「无：异常被捕获不影响主流程」",
            "NEED_MORE_EVIDENCE": "若证据不足、无法确定根因，填写建议补充检索的关键词数组，否则省略",
        }
        return prompts.ANALYZER_SELF_REFINE_REFINE_PROMPT.format(
            review_feedback=review_feedback,
            last_result_text=last_result_text,
            error_log=event.error_log,
            logs_preview=logs_preview,
            evidence_preview=evidence_preview,
            schema_example=json.dumps(schema, ensure_ascii=False)
        )

    def _merge_staged_summary(self, round1: dict | None, round2: dict | None, round3: dict | None) -> str:
        """合并分阶段分析的摘要"""
        def _extract_string_value(value: any) -> str:
            """从值中提取字符串，处理字典情况"""
            if isinstance(value, dict):
                # 优先提取常见字段（包括 phenomenon）
                result = (
                    value.get("direct_cause") 
                    or value.get("summary") 
                    or value.get("description") 
                    or value.get("quick_summary") 
                    or value.get("root_cause")
                    or value.get("phenomenon")
                )
                if result:
                    # 如果提取到的值还是字典，递归处理
                    if isinstance(result, dict):
                        return _extract_string_value(result)
                    return str(result)
                # 如果都没有，尝试将字典转换为可读文本（而不是 JSON）
                result_str = ", ".join(f"{k}: {str(v)}" for k, v in value.items() if v)
                return result_str if result_str else ""
            # 如果是字符串，检查是否是 JSON 格式
            if isinstance(value, str):
                try:
                    parsed = json.loads(value)
                    if isinstance(parsed, dict):
                        # 如果是 JSON 字符串，提取内容
                        return _extract_string_value(parsed)
                except:
                    pass
            return str(value) if value is not None else ""
        
        parts = []
        if round1 and isinstance(round1, dict):
            quick_summary = round1.get("quick_summary") or round1.get("phenomenon")
            if quick_summary:
                quick_summary_str = _extract_string_value(quick_summary)
                if quick_summary_str:
                    parts.append(f"快速定位：{quick_summary_str}")
        if round2 and isinstance(round2, dict):
            root_cause = round2.get("root_cause") or round2.get("direct_cause")
            if root_cause:
                root_cause_str = _extract_string_value(root_cause)
                if root_cause_str:
                    parts.append(f"根本原因：{root_cause_str}")
        if not parts:
            # 如果所有轮次都没有有效摘要，尝试从 round2 或 round3 中提取 summary 字段
            for r in [round2, round3]:
                if r and isinstance(r, dict):
                    summary = r.get("summary")
                    if summary:
                        summary_str = _extract_string_value(summary)
                        if summary_str:
                            return summary_str
            return "已完成分阶段分析，但未获取到有效摘要。"
        result = " ".join(parts)
        # 确保返回的是字符串类型
        return str(result) if result else "已完成分阶段分析，但未获取到有效摘要。"

    def _merge_staged_hypotheses(self, round2: dict | None) -> list[str]:
        """合并分阶段分析的假设"""
        if round2 and isinstance(round2, dict):
            hypotheses = round2.get("hypotheses")
            if isinstance(hypotheses, list):
                return [str(x) for x in hypotheses]
        return []

    def _merge_staged_suggestions(self, round3: dict | None) -> list[str]:
        """合并分阶段分析的建议"""
        if round3 and isinstance(round3, dict):
            suggestions = round3.get("suggestions")
            if isinstance(suggestions, list):
                return [str(x) for x in suggestions]
        return []

    def _is_improvement_significant(self, last_result: dict | None, refine_result: dict | None) -> bool:
        """判断改进是否显著（简化版：比较关键字段）"""
        if not last_result or not refine_result:
            return True
        if not isinstance(last_result, dict) or not isinstance(refine_result, dict):
            return True

        # 比较 summary 长度（简化版）
        def _extract_summary_str(result: dict) -> str:
            """提取 summary 字符串"""
            summary_raw = result.get("summary")
            if isinstance(summary_raw, dict):
                return (
                    summary_raw.get("direct_cause") 
                    or summary_raw.get("summary") 
                    or summary_raw.get("description") 
                    or summary_raw.get("phenomenon")
                    or ""
                )
            return str(summary_raw or "") if summary_raw is not None else ""
        
        last_summary = _extract_summary_str(last_result) if isinstance(last_result, dict) else ""
        refine_summary = _extract_summary_str(refine_result) if isinstance(refine_result, dict) else ""
        if len(refine_summary) > len(last_summary) * 1.1:  # 改进超过10%
            return True

        # 比较 hypotheses 数量
        last_hypotheses = last_result.get("hypotheses") or []
        refine_hypotheses = refine_result.get("hypotheses") or []
        if len(refine_hypotheses) > len(last_hypotheses):
            return True

        return False
