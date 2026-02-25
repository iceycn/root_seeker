from __future__ import annotations

import json
import logging
import re
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable

from root_seeker.domain import (
    AnalysisReport,
    CandidateRepo,
    EvidencePack,
    LogBundle,
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

logger = logging.getLogger(__name__)

# 研发常见错误模式识别提示：帮助 LLM 覆盖全研发过程中的典型问题
_COMMON_ERROR_PATTERNS_HINT = """
【重要】分析时请系统排查以下研发常见错误模式，优先考虑根因而非表象：

1. 接口/方法使用错误：应调用 A 接口却调用了 B 接口（或配置路径指向错误）。若 API 返回某参数错误（如 startTime），但当前 Request 类根本没有该字段，则可能是配置或调用指向了错误接口。修复方向：检查配置路径、调用链，而非盲目在 Request 中新增字段。

2. 空值/空指针：NPE、Optional 未校验、集合为空时直接 get(0)。检查：上游返回值、外部输入、配置项是否可能为 null/空。

3. 类型/格式转换：日期格式不匹配、数字溢出、编码问题。检查：跨系统/跨语言传递时的格式约定、时区、精度。

4. 配置错误：环境配置混用（dev/prod）、配置项缺失、路径/URL 拼写错误、配置被覆盖（如 Apollo 覆盖本地配置）。

5. 并发/竞态：多线程共享可变状态、双重检查锁问题、事务隔离级别不当。检查：是否有未同步的共享变量、锁顺序。

6. 资源/状态：连接未关闭、文件句柄泄漏、状态机非法转换、幂等性缺失导致重复执行。

7. 业务逻辑：边界条件（off-by-one、<= vs <）、条件分支遗漏、使用了错误变量、单位/精度换算错误。

8. 集成边界：超时过短、重试策略不当、熔断未生效、上下游版本不兼容、协议/序列化格式变更。

【业务影响评估】必须输出 business_impact 字段，评估该异常对业务的实际影响程度：
- 高：影响核心流程、用户可见、数据错误、资损风险
- 中：影响部分功能、降级/重试可缓解
- 低：仅影响日志/监控、非关键路径
- 无：异常被捕获、不影响主流程；或仅为告警/调试信息
若异常发生在 try-catch 内且主流程有兜底、或仅为 RPC 反序列化失败但调用方有降级，应标注为「无」或「低」。

【证据不足时请求补充检索】若对某处不清楚、证据不足以确定根因，请明确输出 NEED_MORE_EVIDENCE 字段（字符串数组），列出建议补充检索的关键词（如类名、方法名、配置项、接口路径），交给收集器继续检索。不要给出模棱两可的推测或臆断；宁可承认不确定性并请求补充，也不要含糊其辞。
"""


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

    async def analyze(self, event: NormalizedErrorEvent, *, analysis_id: str | None = None) -> AnalysisReport:
        analysis_id = analysis_id or uuid.uuid4().hex
        logger.info(f"[Analyzer] 开始分析，analysis_id={analysis_id}, service={event.service_name}")

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
                raw_hits = await self._zoekt.search(query=query)
                hits = self._filter_zoekt_hits_for_repo(raw_hits, repo.local_dir, event.service_name)
                hits = self._filter_and_sort_zoekt_hits(hits)
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

        logger.info(f"[Analyzer] 开始生成分析报告，多轮对话模式={self._cfg.llm_multi_turn_mode if self._cfg.llm_multi_turn_enabled else 'single'}")
        report = await self._generate_report(
            analysis_id=analysis_id,
            event=event,
            log_bundle=log_bundle,
            evidence=evidence,
            repo=repo,
        )
        if self._graph_loader is not None:
            graph = self._graph_loader()
            if graph is not None:
                related = []
                related.extend(graph.upstream_of(event.service_name))
                related.extend(graph.downstream_of(event.service_name))
                report = report.model_copy(update={"related_services": related})
                logger.debug(f"[Analyzer] 关联服务：{len(related)} 个")
        self._store.save(report)
        logger.info(f"[Analyzer] 分析完成，analysis_id={analysis_id}, summary长度={len(report.summary)}, 假设数={len(report.hypotheses)}, 建议数={len(report.suggestions)}")
        await self._maybe_notify(report)
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
        terms = [t.strip() for t in query_terms if isinstance(t, str) and t.strip()][:6]
        if not terms:
            return 0
        content_part = "(" + " or ".join(terms) + ")" if len(terms) > 1 else terms[0]
        query = f"repo:{repo.service_name} {content_part}"
        logger.info(f"[Analyzer] 补充检索：{query}")
        try:
            raw_hits = await self._zoekt.search(query=query, max_matches=20)
            hits = self._filter_zoekt_hits_for_repo(raw_hits, repo.local_dir, event.service_name)
            hits = self._filter_and_sort_zoekt_hits(hits)
        except Exception as e:
            logger.warning(f"[Analyzer] 补充 Zoekt 检索失败：{e}", exc_info=True)
            return 0
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
        if terms:
            evidence.notes.append(f"已根据 NEED_MORE_EVIDENCE 补充检索 {len(terms)} 个关键词，追加 {added} 条 Zoekt 证据。")
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
            )

        # 根据配置选择单轮或多轮对话
        if self._cfg.llm_multi_turn_enabled:
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
        system = (
            "你是公司内部的SRE/高级后端工程师。你会基于错误日志、补全日志与代码证据，"
            "输出偏问题排查与定位的结论。输出必须为JSON，不要包含多余文本。"
            + _COMMON_ERROR_PATTERNS_HINT
        )
        user = self._build_llm_user_prompt(event=event, log_bundle=log_bundle, evidence=evidence)
        raw = await self._llm.generate(system=system, user=user)
        parsed = self._try_parse_json(raw)
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

    def _build_llm_user_prompt(
        self, *, event: NormalizedErrorEvent, log_bundle: LogBundle, evidence: EvidencePack
    ) -> str:
        logs_preview = "\n".join(r.message for r in log_bundle.records[:80])
        evidence_preview = self._format_evidence_for_llm(evidence)
        schema = {
            "summary": "一句话到三句话，总结定位结论",
            "hypotheses": ["可能原因1", "可能原因2"],
            "suggestions": ["建议修改1", "建议修改2"],
            "business_impact": "高|中|低|无，可附带说明如「无：异常被捕获不影响主流程」",
            "NEED_MORE_EVIDENCE": "若证据不足、无法确定根因，填写建议补充检索的关键词数组，否则省略",
        }
        return (
            "请根据以下信息进行排查定位并输出JSON。"
            "请结合系统提示中的「研发常见错误模式」进行排查，优先识别根因类型。\n\n"
            f"service_name: {event.service_name}\n"
            f"error_log:\n{event.error_log}\n\n"
            f"enriched_logs (partial):\n{logs_preview}\n\n"
            f"code_evidence:\n{evidence_preview}\n\n"
            f"JSON schema example: {json.dumps(schema, ensure_ascii=False)}\n"
        )

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

    def _try_parse_json(self, raw: str) -> Any:
        raw = raw.strip()
        try:
            return json.loads(raw)
        except Exception:
            pass
        m = re.search(r"\{[\s\S]*\}", raw)
        if m:
            try:
                return json.loads(m.group(0))
            except Exception:
                return {}
        return {}

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
        system = (
            "你是公司内部的SRE/高级后端工程师。你会基于错误日志、补全日志与代码证据，"
            "输出偏问题排查与定位的结论。输出必须为JSON，不要包含多余文本。"
            + _COMMON_ERROR_PATTERNS_HINT
        )
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
            history.add_assistant_message(round1_raw)
            round1_result = self._try_parse_json(round1_raw)

        # Round 2: 深入分析（支持证据不足时补充检索并重试）
        if self._cfg.llm_multi_turn_staged_round2:
            round2_retries = self._cfg.supplementary_evidence_max_retries if self._cfg.supplementary_evidence_enabled else 0
            for retry in range(round2_retries + 1):
                round2_prompt = self._build_staged_round2_prompt(
                    event=event, evidence=evidence, round1_result=round1_result
                )
                history.add_user_message(round2_prompt)
                round2_raw = await self._llm.generate_multi_turn(system=system, messages=history.messages)
                history.add_assistant_message(round2_raw)
                round2_result = self._try_parse_json(round2_raw)
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
                        f"已根据你请求的 NEED_MORE_EVIDENCE 补充检索了 {need_terms}，追加了 {added} 条证据。请基于更新后的证据重新分析。"
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
                history.add_assistant_message(round3_raw)
                round3_result = self._try_parse_json(round3_raw)
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
        system = (
            "你是公司内部的SRE/高级后端工程师。你会基于错误日志、补全日志与代码证据，"
            "输出偏问题排查与定位的结论。输出必须为JSON，不要包含多余文本。"
            + _COMMON_ERROR_PATTERNS_HINT
        )
        history = ConversationHistory()

        # Round 1: 初步分析（支持证据不足时补充检索并重试）
        round1_retries = self._cfg.supplementary_evidence_max_retries if self._cfg.supplementary_evidence_enabled else 0
        round1_result = None
        round1_raw = ""
        for retry in range(round1_retries + 1):
            round1_prompt = self._build_llm_user_prompt(event=event, log_bundle=log_bundle, evidence=evidence)
            history.add_user_message(round1_prompt)
            round1_raw = await self._llm.generate_multi_turn(system=system, messages=history.messages)
            history.add_assistant_message(round1_raw)
            round1_result = self._try_parse_json(round1_raw)
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
                    f"已根据你请求的 NEED_MORE_EVIDENCE 补充检索了 {need_terms}，追加了 {added} 条证据。请基于更新后的证据重新分析。"
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
            history.add_assistant_message(review_raw)
            raw_output += f"\n\n--- Round {i+2} (审查) ---\n" + review_raw

            # 优化分析
            refine_prompt = self._build_self_refine_refine_prompt(
                event=event, log_bundle=log_bundle, evidence=evidence, last_result=last_result, review_feedback=review_raw
            )
            history.add_user_message(refine_prompt)
            refine_raw = await self._llm.generate_multi_turn(system=system, messages=history.messages)
            history.add_assistant_message(refine_raw)
            refine_result = self._try_parse_json(refine_raw)
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
        system = (
            "你是公司内部的SRE/高级后端工程师。你会基于错误日志、补全日志与代码证据，"
            "输出偏问题排查与定位的结论。输出必须为JSON，不要包含多余文本。"
            + _COMMON_ERROR_PATTERNS_HINT
        )
        history = ConversationHistory()

        # 添加分阶段分析的结果作为上下文
        history.add_user_message(
                f"以下是分阶段分析的结果：\n\n"
                f"摘要：{staged_report.summary}\n"
                f"可能原因：{staged_report.hypotheses}\n"
                f"建议：{staged_report.suggestions}\n"
                f"业务影响：{staged_report.business_impact or '未评估'}\n\n"
                f"请审查上述分析，找出需要改进的地方。必须评估业务影响程度（business_impact）。"
        )
        review_raw = await self._llm.generate_multi_turn(system=system, messages=history.messages)
        history.add_assistant_message(review_raw)

        # 基于审查结果优化
        refine_prompt = (
                f"基于以下审查反馈，请优化分析结果：\n\n"
                f"审查反馈：{review_raw}\n\n"
                f"原始错误日志：\n{event.error_log}\n\n"
                f"请输出优化后的JSON格式分析结果，必须包含 business_impact（高|中|低|无，可附带说明）。"
        )
        history.add_user_message(refine_prompt)
        refine_raw = await self._llm.generate_multi_turn(system=system, messages=history.messages)
        refine_result = self._try_parse_json(refine_raw)

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
        )

    def _build_staged_round1_prompt(self, *, event: NormalizedErrorEvent) -> str:
        """构建阶段1：快速定位的 prompt"""
        schema = {
            "problem_location": "文件路径:行号（从堆栈中提取）",
            "error_type": "异常类型",
            "quick_summary": "一句话总结问题",
        }
        return (
            "请快速定位以下错误：\n\n"
            f"错误日志：\n{event.error_log}\n\n"
            f"请输出JSON格式：\n{json.dumps(schema, ensure_ascii=False)}"
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
        return (
            "基于第一轮的定位结果，请深入分析根本原因。"
            "请结合系统提示中的「研发常见错误模式」进行排查：接口/方法使用错误、空值、配置、并发、资源、业务逻辑、集成边界等，优先识别根因类型再给出假设。\n\n"
            f"{round1_text}"
            f"相关代码证据：\n{evidence_preview}\n\n"
            f"请输出JSON格式：\n{json.dumps(schema, ensure_ascii=False)}"
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

        logs_preview = "\n".join(r.message for r in log_bundle.records[:40])
        schema = {
            "suggestions": ["建议1（具体可操作）", "建议2", "建议3"],
            "priority": "高/中/低",
            "business_impact": "高|中|低|无，可附带说明如「无：异常被捕获不影响主流程」",
            "implementation_hints": "实现提示（可选）",
        }
        return (
            "基于前两轮的分析结果，请生成具体的修复建议。必须评估业务影响程度（business_impact）：若异常被捕获、有兜底、或 RPC 失败但调用方有降级，应标注为「无」或「低」。\n\n"
            f"{round1_text}"
            f"{round2_text}"
            f"补全日志（上下文）：\n{logs_preview}\n\n"
            f"请输出JSON格式：\n{json.dumps(schema, ensure_ascii=False)}"
        )

    def _build_self_refine_review_prompt(self, last_result: dict | None) -> str:
        """构建 Self-Refine 审查 prompt"""
        result_text = json.dumps(last_result, ensure_ascii=False) if last_result else "无"
        schema = {
            "review_feedback": ["反馈1", "反馈2"],
            "needs_improvement": ["需要改进的地方1", "需要改进的地方2"],
        }
        return (
            "请审查上述分析结果，找出：\n"
            "1. 哪些原因分析不够深入？\n"
            "2. 哪些关键证据被遗漏？\n"
            "3. 哪些建议不够具体？\n\n"
            f"分析结果：\n{result_text}\n\n"
            f"请输出JSON格式：\n{json.dumps(schema, ensure_ascii=False)}"
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
        logs_preview = "\n".join(r.message for r in log_bundle.records[:80])
        evidence_preview = self._format_evidence_for_llm(evidence)
        last_result_text = json.dumps(last_result, ensure_ascii=False) if last_result else "无"

        schema = {
            "summary": "一句话到三句话，总结定位结论",
            "hypotheses": ["可能原因1", "可能原因2"],
            "suggestions": ["建议修改1", "建议修改2"],
            "business_impact": "高|中|低|无，可附带说明如「无：异常被捕获不影响主流程」",
            "NEED_MORE_EVIDENCE": "若证据不足、无法确定根因，填写建议补充检索的关键词数组，否则省略",
        }
        return (
            "基于审查反馈，请优化分析结果。必须评估业务影响程度（business_impact）。\n\n"
            f"审查反馈：\n{review_feedback}\n\n"
            f"上一轮分析结果：\n{last_result_text}\n\n"
            f"错误日志：\n{event.error_log}\n\n"
            f"补全日志：\n{logs_preview}\n\n"
            f"代码证据：\n{evidence_preview}\n\n"
            f"请输出优化后的JSON格式：\n{json.dumps(schema, ensure_ascii=False)}"
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
