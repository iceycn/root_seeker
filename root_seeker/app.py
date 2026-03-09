from __future__ import annotations

import asyncio
import dataclasses
import logging
import os
import sys
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

# 使用 HuggingFace 国内镜像，便于 fastembed 拉取模型（用户已设置 HF_ENDPOINT 则不改）
os.environ.setdefault("HF_ENDPOINT", "https://hf-mirror.com")

from fastapi import Depends, FastAPI, HTTPException, Request


def setup_logging(log_level: str = "INFO") -> None:
    """配置日志系统"""
    level = getattr(logging, log_level.upper(), logging.INFO)
    logging.basicConfig(
        level=level,
        format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
        stream=sys.stdout,
    )
    # 设置第三方库日志级别
    logging.getLogger("httpx").setLevel(logging.WARNING)
    logging.getLogger("httpcore").setLevel(logging.WARNING)
    logging.getLogger("uvicorn").setLevel(logging.INFO)
    logging.getLogger("fastapi").setLevel(logging.INFO)

from root_seeker.config import get_config_db, load_config
from root_seeker.domain import IngestEvent, NormalizedErrorEvent
from root_seeker.providers.llm import OpenAICompatConfig, OpenAICompatLLM
from root_seeker.providers.embedding import FastEmbedConfig, FastEmbedProvider, HashEmbeddingProvider
from root_seeker.providers.llm_wrapped import LlmRuntimeConfig, RateLimitedCircuitBreakerLLM
from root_seeker.providers.notifiers import (
    ConsoleNotifier,
    DingTalkNotifier,
    DingTalkNotifierConfig,
    FileReportStoreNotifier,
    FileReportStoreNotifierConfig,
    WeComNotifier,
    WeComNotifierConfig,
)
from root_seeker.providers.sls import AliyunSlsProvider, AliyunSlsQueryConfig
from root_seeker.providers.trace_chain import (
    AliyunTraceChainProvider,
    AliyunTraceChainProviderConfig,
    EmptyTraceChainProvider,
    TraceChainProvider,
)
from root_seeker.providers.zoekt import ZoektClient, ZoektClientConfig
from root_seeker.providers.qdrant import QdrantConfig, QdrantVectorStore
from root_seeker.services.analyzer import AnalyzerConfig, AnalyzerService
from root_seeker.services.enricher import EnrichmentConfig, LogEnricher
from root_seeker.services.evidence import EvidenceBuilder, EvidenceLimits
from root_seeker.indexing.chunker import TreeSitterChunker
from root_seeker.services.router import RepoCatalog, ServiceRouter
from root_seeker.services.vector_retriever import VectorRetriever, VectorSearchConfig
from root_seeker.services.vector_indexer import VectorIndexer, VectorIndexConfig
from root_seeker.services.service_graph import ServiceGraphBuilder, load_graph, save_graph
from root_seeker.sql_templates import SqlTemplate, SqlTemplateRegistry
from root_seeker.storage.analysis_store import AnalysisStore
from root_seeker.storage.audit_log import AuditLogger
from root_seeker.storage.status_store import StatusStore
from root_seeker.storage.db_status_store import save_status_to_db
from root_seeker.events import (
    AnalysisEventBus,
    GraphRebuildCompletedEvent,
    GraphRebuildCompletedEventBus,
    GraphRebuildCompletedLogListener,
    GraphRebuildEventBus,
    GraphRebuildLogListener,
    GraphRebuildQueuedEvent,
    QdrantIndexRemovedEvent,
    QdrantIndexRemovedEventBus,
    QdrantIndexRemovedLogListener,
    QdrantIndexSyncReceiver,
    QdrantRemoveReceiver,
    RepoSyncCompletedToRequestSyncBridge,
    RepoIndexSyncEvent,
    RepoIndexSyncEventBus,
    RepoIndexSyncLogListener,
    RequestFullReloadEvent,
    RequestFullReloadEventBus,
    RequestFullReloadLogListener,
    RequestRemoveRepoEvent,
    RequestRemoveRepoEventBus,
    RequestRemoveRepoLogListener,
    RequestResyncRepoEvent,
    RequestResyncRepoEventBus,
    RequestResyncRepoLogListener,
    ResyncCompletedEvent,
    ResyncReceiver,
    ResyncCompletedEventBus,
    ResyncCompletedLogListener,
    RequestResetAllEvent,
    RequestResetAllEventBus,
    RequestResetAllLogListener,
    RequestSyncRepoEvent,
    RequestSyncRepoEventBus,
    RequestSyncRepoLogListener,
    LogListener,
    new_correlation_id,
    NotifierCompletionListener,
    QdrantIndexCompletedEvent,
    QdrantIndexEventBus,
    QdrantIndexLogListener,
    RepoSyncCompletedEvent,
    RepoSyncEventBus,
    RepoSyncLogListener,
    ZoektIndexCompletedEvent,
    ZoektIndexCompletedEventBus,
    ZoektIndexLogListener,
    ZoektIndexRemovedEvent,
    ZoektIndexRemovedEventBus,
    ZoektIndexRemovedLogListener,
    ZoektIndexSyncReceiver,
    ZoektRemoveReceiver,
)
from root_seeker.runtime.job_queue import Job, JobQueue
from root_seeker.runtime.periodic_tasks import PeriodicTaskConfig, PeriodicTaskService
from root_seeker.runtime.graph_rebuild_queue import GraphRebuildQueue
from root_seeker.security import build_api_key_dependency
from root_seeker.services.repo_mirror import RepoMirror, RepoSyncResult
from root_seeker.services.log_clusterer import LogClusterer
from root_seeker.ingest import parse_ingest_body, parse_log_list, to_normalized_event
from root_seeker.git_source import GitSourceService, create_storage_from_config
from root_seeker.indexing.queue import (
    IndexTaskStatus,
    IndexTaskType,
    InMemoryIndexingQueue,
)


def create_app() -> FastAPI:
    cfg = load_config().app
    # 配置日志系统
    setup_logging(cfg.log_level)
    app_logger = logging.getLogger(__name__)
    app_logger.info(f"[App] 应用启动，日志级别={cfg.log_level}")
    
    app = FastAPI(title="RootSeeker", version="0.1.0")

    def _dedup_repos(repos: list[RepoConfig]) -> list[RepoConfig]:
        seen: dict[str, RepoConfig] = {}
        for r in repos:
            sn = (r.service_name or "").strip()
            if not sn:
                continue
            prev = seen.get(sn)
            if prev is None:
                seen[sn] = r
                continue
            if prev.local_dir == r.local_dir and prev.git_url == r.git_url:
                continue
            app_logger.warning(
                "[App] 仓库 service_name 重复，保留第一条并忽略后续: service_name=%s local_dir=%s ignored_local_dir=%s",
                sn,
                prev.local_dir,
                r.local_dir,
            )
        return list(seen.values())

    # 提前初始化 git_source 以合并仓库到 catalog（用于分析与索引）
    git_source_service: GitSourceService | None = None
    repos_for_catalog = list(cfg.repos)
    if cfg.git_source is None or cfg.git_source.enabled:
        storage_config = cfg.git_source.storage if cfg.git_source else {"type": "file", "file_path": "data/git_source.json"}
        repos_base = cfg.git_source.repos_base_dir if cfg.git_source else "data/repos_from_git"
        storage = create_storage_from_config(storage_config)
        git_source_service = GitSourceService(storage=storage, repos_base_dir=repos_base)
        git_repos = git_source_service.get_enabled_repos_as_config()
        repos_for_catalog = _dedup_repos(list(cfg.repos) + git_repos)
        app_logger.info("[App] Git 仓库发现服务已启用")

    catalog = RepoCatalog(repos=repos_for_catalog)
    router = ServiceRouter(catalog=catalog)

    registry = SqlTemplateRegistry(
        templates=[SqlTemplate(query_key=t.query_key, query=t.query) for t in cfg.sql_templates]
    )
    sls_provider = AliyunSlsProvider(
        AliyunSlsQueryConfig(
            endpoint=cfg.aliyun_sls.endpoint,
            access_key_id=cfg.aliyun_sls.access_key_id,
            access_key_secret=cfg.aliyun_sls.access_key_secret,
            project=cfg.aliyun_sls.project,
            logstore=cfg.aliyun_sls.logstore,
            topic=cfg.aliyun_sls.topic,
        )
    )

    data_dir = Path(cfg.data_dir)
    store = AnalysisStore(base_dir=data_dir / "analyses")
    graph_path = data_dir / "service_graph.json"
    graph_loader = lambda: load_graph(graph_path)
    status_store = StatusStore(base_dir=data_dir / "status")
    audit_logger = AuditLogger(path=Path(cfg.audit_dir) / "audit.jsonl")
    require_api_key = build_api_key_dependency(cfg.api_keys)

    # 初始化 LLM（需要在 LogEnricher 之前创建）
    llm = None
    llm_client_to_close = None
    if cfg.llm is not None and str(cfg.llm.api_key or "").strip():
        use_chat_url = cfg.llm.kind == "doubao"
        base_llm = OpenAICompatLLM(
            OpenAICompatConfig(
                base_url=str(cfg.llm.base_url),
                api_key=cfg.llm.api_key,
                model=cfg.llm.model,
                timeout_seconds=cfg.llm.timeout_seconds,
                chat_url=str(cfg.llm.base_url) if use_chat_url else None,
                temperature=cfg.llm.temperature,
                max_tokens=cfg.llm.max_tokens,
            )
        )
        llm_client_to_close = base_llm
        llm = RateLimitedCircuitBreakerLLM(
            inner=base_llm,
            cfg=LlmRuntimeConfig(concurrency=cfg.llm_concurrency),
            audit=audit_logger,
        )
    elif cfg.llm is not None:
        app_logger.info("[App] 未配置 LLM api_key，已禁用云端 LLM（仅做检索与证据收集）")

    enrichment_cfg = EnrichmentConfig(
        time_window_seconds=300,
        trace_chain_enabled=cfg.trace_chain_enabled,
        trace_chain_time_window_seconds=cfg.trace_chain_time_window_seconds,
    )
    
    # 初始化 trace_chain_provider：如果配置了阿里云 SLS，使用 AliyunTraceChainProvider；否则使用空实现
    trace_chain_provider: TraceChainProvider | None = None
    if cfg.trace_chain_enabled and cfg.aliyun_sls is not None:
        trace_chain_provider = AliyunTraceChainProvider(
            AliyunTraceChainProviderConfig(
                endpoint=cfg.aliyun_sls.endpoint,
                access_key_id=cfg.aliyun_sls.access_key_id,
                access_key_secret=cfg.aliyun_sls.access_key_secret,
                project=cfg.aliyun_sls.project,
                logstore=cfg.aliyun_sls.logstore,
                topic=cfg.aliyun_sls.topic,
                max_time_window_seconds=cfg.max_trace_chain_time_window_seconds,
            )
        )
        app_logger.info(
            f"[App] 已配置 AliyunTraceChainProvider，最大时间窗口={cfg.max_trace_chain_time_window_seconds}秒"
        )
    else:
        trace_chain_provider = EmptyTraceChainProvider()
        app_logger.debug("[App] 使用 EmptyTraceChainProvider（未配置或未启用）")
    
    enricher = LogEnricher(
        registry=registry,
        provider=sls_provider,
        cfg=enrichment_cfg,
        llm=llm,
        trace_chain_provider=trace_chain_provider,
    )

    zoekt = None
    if cfg.zoekt is not None:
        zoekt = ZoektClient(ZoektClientConfig(api_base_url=str(cfg.zoekt.api_base_url)))

    notifiers: list = []
    if cfg.wecom is not None:
        notifiers.append(
            WeComNotifier(
                WeComNotifierConfig(
                    webhook_url=str(cfg.wecom.webhook_url),
                    secret=cfg.wecom.secret,
                    security_mode=cfg.wecom.security_mode or "ip",
                )
            )
        )
    if cfg.dingtalk is not None:
        notifiers.append(
            DingTalkNotifier(
                DingTalkNotifierConfig(
                    webhook_url=str(cfg.dingtalk.webhook_url),
                    secret=cfg.dingtalk.secret,
                    security_mode=cfg.dingtalk.security_mode or "sign",
                )
            )
        )
    if cfg.notify_console:
        notifiers.append(ConsoleNotifier())
    if cfg.report_store_path:
        notifiers.append(FileReportStoreNotifier(FileReportStoreNotifierConfig(path=cfg.report_store_path)))
    evidence_builder = EvidenceBuilder(
        EvidenceLimits(
            max_files=cfg.max_evidence_files,
            max_chars_total=cfg.max_context_chars_total,
            max_chars_per_file=cfg.max_context_chars_per_file,
        )
    )

    embedder = None
    qstore = None
    vector = None
    if cfg.qdrant is not None and cfg.embedding is not None:
        if cfg.embedding.kind == "hash":
            embedder = HashEmbeddingProvider()
        else:
            model_name = cfg.embedding.model_name or "BAAI/bge-small-en-v1.5"
            embedder = FastEmbedProvider(
                FastEmbedConfig(model_name=model_name, cache_dir=cfg.embedding.cache_dir)
            )
        qstore = QdrantVectorStore(
            QdrantConfig(
                url=cfg.qdrant.url,
                api_key=cfg.qdrant.api_key,
                collection=cfg.qdrant.collection,
                timeout=getattr(cfg.qdrant, "timeout", 30),
            )
        )
        vector = VectorRetriever(cfg=VectorSearchConfig(top_k=12), embedder=embedder, store=qstore)

    vector_indexer = None
    if embedder is not None and qstore is not None:
        vector_indexer = VectorIndexer(
            cfg=VectorIndexConfig(batch_size=64),
            chunker=TreeSitterChunker(),
            embedder=embedder,
            store=qstore,
        )

    analyzer = AnalyzerService(
        cfg=AnalyzerConfig(
            evidence_level=cfg.evidence_level,
            cross_repo_evidence=cfg.cross_repo_evidence,
            cross_repo_max_services=cfg.cross_repo_max_services,
            cross_repo_max_chunks_per_service=cfg.cross_repo_max_chunks_per_service,
            call_graph_expansion=cfg.call_graph_expansion,
            call_graph_max_rounds=cfg.call_graph_max_rounds,
            call_graph_max_methods_per_round=cfg.call_graph_max_methods_per_round,
            call_graph_max_total_methods=cfg.call_graph_max_total_methods,
            llm_multi_turn_enabled=cfg.llm_multi_turn_enabled,
            llm_multi_turn_mode=cfg.llm_multi_turn_mode,
            llm_multi_turn_max_rounds=cfg.llm_multi_turn_max_rounds,
            llm_multi_turn_enable_self_review=cfg.llm_multi_turn_enable_self_review,
            llm_multi_turn_staged_round1=cfg.llm_multi_turn_staged_round1,
            llm_multi_turn_staged_round2=cfg.llm_multi_turn_staged_round2,
            llm_multi_turn_staged_round3=cfg.llm_multi_turn_staged_round3,
            llm_multi_turn_self_refine_review_rounds=cfg.llm_multi_turn_self_refine_review_rounds,
            llm_multi_turn_self_refine_improvement_threshold=cfg.llm_multi_turn_self_refine_improvement_threshold,
        ),
        router=router,
        enricher=enricher,
        zoekt=zoekt,
        vector=vector,
        graph_loader=graph_loader,
        evidence_builder=evidence_builder,
        llm=llm,
        notifiers=[],  # 通知改由完成事件监听器推送（NotifierCompletionListener）
        store=store,
    )

    event_bus = AnalysisEventBus()
    event_bus.add_listener(LogListener(pretty=True))
    if notifiers:
        event_bus.add_listener(NotifierCompletionListener(notifiers))

    repoSyncEventBus = RepoSyncEventBus()
    repoSyncEventBus.add_listener(RepoSyncLogListener())

    qdrantIndexEventBus = QdrantIndexEventBus()
    qdrantIndexEventBus.add_listener(QdrantIndexLogListener())

    graphRebuildEventBus = GraphRebuildEventBus()
    graphRebuildEventBus.add_listener(GraphRebuildLogListener())

    repoIndexSyncEventBus = RepoIndexSyncEventBus()
    repoIndexSyncEventBus.add_listener(RepoIndexSyncLogListener())

    requestSyncRepoEventBus = RequestSyncRepoEventBus()
    requestSyncRepoEventBus.add_listener(RequestSyncRepoLogListener())

    requestRemoveRepoEventBus = RequestRemoveRepoEventBus()
    requestRemoveRepoEventBus.add_listener(RequestRemoveRepoLogListener())

    requestResyncRepoEventBus = RequestResyncRepoEventBus()
    requestResyncRepoEventBus.add_listener(RequestResyncRepoLogListener())

    resyncCompletedEventBus = ResyncCompletedEventBus()
    resyncCompletedEventBus.add_listener(ResyncCompletedLogListener())

    requestResetAllEventBus = RequestResetAllEventBus()
    requestResetAllEventBus.add_listener(RequestResetAllLogListener())

    requestFullReloadEventBus = RequestFullReloadEventBus()
    requestFullReloadEventBus.add_listener(RequestFullReloadLogListener())

    qdrantIndexRemovedEventBus = QdrantIndexRemovedEventBus()
    qdrantIndexRemovedEventBus.add_listener(QdrantIndexRemovedLogListener())

    zoektIndexRemovedEventBus = ZoektIndexRemovedEventBus()
    zoektIndexRemovedEventBus.add_listener(ZoektIndexRemovedLogListener())

    zoektIndexEventBus = ZoektIndexCompletedEventBus()
    zoektIndexEventBus.add_listener(ZoektIndexLogListener())

    graphRebuildCompletedEventBus = GraphRebuildCompletedEventBus()
    graphRebuildCompletedEventBus.add_listener(GraphRebuildCompletedLogListener())

    config_db = get_config_db()
    def _db_status_sync(st, service_name, repo_id=None):
        if config_db:
            save_status_to_db(
                host=config_db.get("host", "localhost"),
                port=int(config_db.get("port", 3306)),
                user=config_db.get("user", "root"),
                password=config_db.get("password", ""),
                database=config_db.get("database", "root_seeker"),
                status=st,
                service_name=service_name,
                repo_id=repo_id,
            )
    job_queue = JobQueue(
        analyzer=analyzer,
        status_store=status_store,
        store=store,
        event_bus=event_bus,
        workers=cfg.analysis_workers,
        timeout_seconds=cfg.analysis_timeout_seconds,
        db_status_sync=_db_status_sync if config_db else None,
    )
    ssh_known_hosts_file = str((data_dir / "ssh" / "known_hosts").resolve())
    def _credential_provider(git_url: str):
        if not git_source_service:
            return None
        cred = git_source_service.get_credential()
        if not cred:
            return None
        from urllib.parse import urlparse
        parsed = urlparse(git_url)
        host = parsed.hostname or ""
        domain = cred.domain.strip().lower().replace("https://", "").replace("http://", "")
        domain = domain.split("/", 1)[0]
        if not host or not domain:
            return None
        allow_hosts = {domain}
        if getattr(cred, "platform", "") == "codeup":
            allow_hosts.add("codeup.aliyun.com")
            if "openapi-rdc.aliyuncs.com" in domain:
                allow_hosts.add("codeup.aliyun.com")
        if host.lower() in allow_hosts:
            return (cred.username, cred.password)
        return None
    repo_mirror = RepoMirror(
        git_timeout_seconds=cfg.git_timeout_seconds,
        ssh_known_hosts_file=ssh_known_hosts_file,
        ssh_keyscan_hosts=[],
        credential_provider=_credential_provider,
    )
    
    # 创建定时任务服务
    log_clusterer = LogClusterer(
        embedder=embedder,
        similarity_threshold=0.88,
        max_logs_for_embedding=2000,
    )

    # 合并 config.repos 与 git_source 已启用的仓库，供 periodic 同步
    repos_for_sync = list(cfg.repos)
    if git_source_service:
        git_repos = git_source_service.get_enabled_repos_as_config()
        repos_for_sync = _dedup_repos(list(cfg.repos) + git_repos)
        if git_repos:
            app_logger.info(f"[App] 已合并 {len(git_repos)} 个 Git 发现仓库到同步列表")

    index_semaphore = asyncio.Semaphore(cfg.auto_index_concurrency)
    indexing_qdrant: set[str] = set()  # 同步索引（reset/full-reload）进行中的 service_name
    recently_indexed_zoekt: set[str] = set()  # 近期成功索引的 service_name（/api/list 不可用时作为回退）

    # 索引队列（策略模式，默认内存队列）
    index_queue: InMemoryIndexingQueue | None = None
    if cfg.indexing_queue == "memory":
        index_queue = InMemoryIndexingQueue(max_history=500)

        async def _run_qdrant(task) -> None:
            candidates = router.route(task.service_name)
            if not candidates:
                task.status = IndexTaskStatus.FAILED
                task.error = "service_name not mapped"
                return
            repo = candidates[0]
            extra = task.result if isinstance(task.result, dict) else {}
            incremental = extra.get("incremental", False)
            skip_if_already_indexed = extra.get("skip_if_already_indexed", False)
            correlation_id = extra.get("correlation_id")
            app_logger.info(
                "[IndexQueue] 队列被消费，开始处理 Qdrant 索引 job_id=%s service=%s",
                task.job_id,
                task.service_name,
            )
            # no_change 且 Qdrant 已有索引：跳过索引，打印日志并回调
            if skip_if_already_indexed and qstore is not None:
                try:
                    count = await asyncio.wait_for(
                        asyncio.to_thread(qstore.count_points_by_service, service_name=task.service_name),
                        timeout=15.0,
                    )
                    if count > 0:
                        app_logger.info(
                            "[IndexQueue] 仓库已索引，跳过索引并回调 service=%s count=%d",
                            task.service_name,
                            count,
                        )
                        task.result = count
                        task.status = IndexTaskStatus.COMPLETED
                        task.append_log(f"仓库已索引（块数={count}），跳过并回调")
                        qdrantIndexEventBus.emit(
                            QdrantIndexCompletedEvent(
                                service_name=task.service_name,
                                repo_local_dir=repo.local_dir,
                                indexed_chunks=count,
                                status="completed",
                                correlation_id=correlation_id,
                                callback_url=task.callback_url,
                            )
                        )
                        return
                except (asyncio.TimeoutError, Exception) as e:
                    app_logger.warning("[IndexQueue] 检查已索引失败，继续执行索引: %s", e)

            task.append_log(f"索引仓库 {repo.local_dir}")

            try:
                async with index_semaphore:
                    count = await vector_indexer.index_repo(
                        repo_local_dir=repo.local_dir,
                        service_name=task.service_name,
                        incremental=incremental,
                    )
                task.result = count
                task.status = IndexTaskStatus.COMPLETED
                task.append_log(f"完成，索引块数={count}")
                qdrantIndexEventBus.emit(
                    QdrantIndexCompletedEvent(
                        service_name=task.service_name,
                        repo_local_dir=repo.local_dir,
                        indexed_chunks=count,
                        status="completed",
                        correlation_id=correlation_id,
                        callback_url=task.callback_url,
                    )
                )
            except Exception as e:
                task.status = IndexTaskStatus.FAILED
                task.error = str(e)
                task.append_log(f"失败: {e}")
                qdrantIndexEventBus.emit(
                    QdrantIndexCompletedEvent(
                        service_name=task.service_name,
                        repo_local_dir=repo.local_dir,
                        indexed_chunks=0,
                        status="failed",
                        error=str(e),
                        correlation_id=correlation_id,
                        callback_url=task.callback_url,
                    )
                )

        async def _run_zoekt(task) -> None:
            import shutil
            import tempfile
            candidates = router.route(task.service_name)
            if not candidates:
                task.status = IndexTaskStatus.FAILED
                task.error = "service_name not mapped"
                return
            repo = candidates[0]
            extra = task.result if isinstance(task.result, dict) else {}
            skip_if_already_indexed = extra.get("skip_if_already_indexed", False)
            correlation_id = extra.get("correlation_id")
            index_dir = data_dir / "zoekt" / "index"
            # no_change 且 Zoekt 已有索引：跳过索引，打印日志并回调
            if skip_if_already_indexed and index_dir.exists():
                has_index = any(
                    task.service_name in p.name
                    for p in index_dir.iterdir()
                    if p.is_file()
                )
                if has_index:
                    app_logger.info(
                        "[IndexQueue] 仓库已索引（Zoekt），跳过索引并回调 service=%s",
                        task.service_name,
                    )
                    task.result = "Zoekt 索引完成"
                    task.status = IndexTaskStatus.COMPLETED
                    task.append_log("仓库已索引，跳过并回调")
                    zoektIndexEventBus.emit(
                        ZoektIndexCompletedEvent(
                            service_name=task.service_name,
                            repo_local_dir=repo.local_dir,
                            status="completed",
                            correlation_id=correlation_id,
                            callback_url=task.callback_url,
                        )
                    )
                    return
            zoekt_index = shutil.which("zoekt-index")
            if not zoekt_index:
                gobin = os.environ.get("GOPATH", "")
                if gobin:
                    cand = Path(gobin) / "bin" / "zoekt-index"
                    if cand.exists():
                        zoekt_index = str(cand)
                if not zoekt_index:
                    for base in (Path.home() / "go", Path("/usr/local/go")):
                        cand = base / "bin" / "zoekt-index"
                        if cand.exists():
                            zoekt_index = str(cand)
                            break
            if not zoekt_index or not Path(zoekt_index).exists():
                task.status = IndexTaskStatus.FAILED
                task.error = "zoekt-index 未找到"
                return
            index_dir.mkdir(parents=True, exist_ok=True)
            index_target = Path(repo.local_dir).resolve()
            tmpdir_cleanup: Path | None = None
            if index_target.name != task.service_name:
                tmpdir_cleanup = Path(tempfile.mkdtemp(prefix="zoekt-index-"))
                try:
                    link_path = tmpdir_cleanup / task.service_name
                    link_path.symlink_to(index_target)
                    index_target = link_path
                except OSError:
                    if tmpdir_cleanup.exists():
                        shutil.rmtree(tmpdir_cleanup, ignore_errors=True)
                    task.status = IndexTaskStatus.FAILED
                    task.error = f"无法创建符号链接"
                    return
            try:
                task.append_log(f"执行 zoekt-index -index {index_dir} {index_target}")
                proc = await asyncio.create_subprocess_exec(
                    zoekt_index,
                    "-index", str(index_dir),
                    str(index_target),
                    stdout=asyncio.subprocess.PIPE,
                    stderr=asyncio.subprocess.PIPE,
                )
                stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=600)
                if stdout:
                    for line in stdout.decode("utf-8", errors="replace").strip().splitlines():
                        task.append_log(line)
                if stderr:
                    for line in stderr.decode("utf-8", errors="replace").strip().splitlines():
                        task.append_log(f"[stderr] {line}")
                if proc.returncode != 0:
                    task.status = IndexTaskStatus.FAILED
                    task.error = (stderr or stdout or b"").decode("utf-8", errors="replace").strip()[:500]
                    return
                recently_indexed_zoekt.add(task.service_name)
                task.result = "Zoekt 索引完成"
                task.status = IndexTaskStatus.COMPLETED
                task.append_log("完成")
                zoektIndexEventBus.emit(
                    ZoektIndexCompletedEvent(
                        service_name=task.service_name,
                        repo_local_dir=repo.local_dir,
                        status="completed",
                        correlation_id=correlation_id,
                        callback_url=task.callback_url,
                    )
                )
            except asyncio.TimeoutError:
                task.status = IndexTaskStatus.FAILED
                task.error = "zoekt-index 超时"
            finally:
                if tmpdir_cleanup is not None and tmpdir_cleanup.exists():
                    shutil.rmtree(tmpdir_cleanup, ignore_errors=True)

        async def _run_remove_qdrant(task) -> None:
            extra = task.result if isinstance(task.result, dict) else {}
            correlation_id = extra.get("correlation_id")
            app_logger.info(
                "[IndexQueue] 队列被消费，开始处理 Qdrant 移除 job_id=%s service=%s",
                task.job_id,
                task.service_name,
            )
            # 若 Qdrant 未索引该仓库：跳过清除，打印日志并回调
            if qstore is not None:
                try:
                    count = await asyncio.wait_for(
                        asyncio.to_thread(qstore.count_points_by_service, service_name=task.service_name),
                        timeout=15.0,
                    )
                    if count == 0:
                        app_logger.info(
                            "[IndexQueue] 仓库未索引（Qdrant），跳过清除并回调 service=%s",
                            task.service_name,
                        )
                        task.status = IndexTaskStatus.COMPLETED
                        task.append_log("仓库未索引，跳过清除并回调")
                        qdrantIndexRemovedEventBus.emit(
                            QdrantIndexRemovedEvent(
                                service_name=task.service_name,
                                status="completed",
                                correlation_id=correlation_id,
                                callback_url=task.callback_url,
                            )
                        )
                        return
                except (asyncio.TimeoutError, Exception) as e:
                    app_logger.warning("[IndexQueue] 检查 Qdrant 索引失败，继续执行清除: %s", e)
            try:
                await asyncio.to_thread(qstore.delete_points_by_service, service_name=task.service_name)
                task.status = IndexTaskStatus.COMPLETED
                task.append_log("完成")
                qdrantIndexRemovedEventBus.emit(
                    QdrantIndexRemovedEvent(
                        service_name=task.service_name,
                        status="completed",
                        correlation_id=correlation_id,
                        callback_url=task.callback_url,
                    )
                )
            except Exception as e:
                task.status = IndexTaskStatus.FAILED
                task.error = str(e)
                task.append_log(f"失败: {e}")
                qdrantIndexRemovedEventBus.emit(
                    QdrantIndexRemovedEvent(
                        service_name=task.service_name,
                        status="failed",
                        error=str(e),
                        correlation_id=correlation_id,
                        callback_url=task.callback_url,
                    )
                )

        async def _run_remove_zoekt(task) -> None:
            import glob
            extra = task.result if isinstance(task.result, dict) else {}
            correlation_id = extra.get("correlation_id")
            app_logger.info(
                "[IndexQueue] 队列被消费，开始处理 Zoekt 移除 job_id=%s service=%s",
                task.job_id,
                task.service_name,
            )
            zoekt_index_dir = data_dir / "zoekt" / "index"
            # 若 Zoekt 未索引该仓库：跳过清除，打印日志并回调
            has_index = (
                zoekt_index_dir.exists()
                and any(
                    p.is_file() and task.service_name in p.name
                    for p in zoekt_index_dir.iterdir()
                )
            )
            if not has_index:
                    app_logger.info(
                        "[IndexQueue] 仓库未索引（Zoekt），跳过清除并回调 service=%s",
                        task.service_name,
                    )
                    task.status = IndexTaskStatus.COMPLETED
                    task.append_log("仓库未索引，跳过清除并回调")
                    zoektIndexRemovedEventBus.emit(
                        ZoektIndexRemovedEvent(
                            service_name=task.service_name,
                            status="completed",
                            correlation_id=correlation_id,
                            callback_url=task.callback_url,
                        )
                    )
                    return
            try:
                if zoekt_index_dir.exists():
                    for f in glob.glob(str(zoekt_index_dir / "*")):
                        p = Path(f)
                        if p.is_file() and task.service_name in p.name:
                            p.unlink(missing_ok=True)
                recently_indexed_zoekt.discard(task.service_name)
                task.status = IndexTaskStatus.COMPLETED
                task.append_log("完成")
                zoektIndexRemovedEventBus.emit(
                    ZoektIndexRemovedEvent(
                        service_name=task.service_name,
                        status="completed",
                        correlation_id=correlation_id,
                        callback_url=task.callback_url,
                    )
                )
            except Exception as e:
                task.status = IndexTaskStatus.FAILED
                task.error = str(e)
                task.append_log(f"失败: {e}")
                zoektIndexRemovedEventBus.emit(
                    ZoektIndexRemovedEvent(
                        service_name=task.service_name,
                        status="failed",
                        error=str(e),
                        correlation_id=correlation_id,
                        callback_url=task.callback_url,
                    )
                )

        repoSyncEventBus.add_listener(
            RepoSyncCompletedToRequestSyncBridge(request_sync_repo_event_bus=requestSyncRepoEventBus)
        )
        requestSyncRepoEventBus.add_listener(
            QdrantIndexSyncReceiver(
                index_queue=index_queue,
                repo_index_sync_event_bus=repoIndexSyncEventBus,
            )
        )
        requestSyncRepoEventBus.add_listener(
            ZoektIndexSyncReceiver(
                index_queue=index_queue,
                repo_index_sync_event_bus=repoIndexSyncEventBus,
            )
        )

    def _get_repos_for_graph():
        repos = list(cfg.repos)
        if git_source_service:
            repos = repos + git_source_service.get_enabled_repos_as_config()
        return _dedup_repos(repos)

    def _on_graph_rebuild_queued(event_id: str, correlation_id: str | None) -> None:
        graphRebuildEventBus.emit(
            GraphRebuildQueuedEvent(event_id=event_id, correlation_id=correlation_id)
        )

    def _on_graph_rebuild_completed(edge_count: int, correlation_id: str | None) -> None:
        graphRebuildCompletedEventBus.emit(
            GraphRebuildCompletedEvent(edge_count=edge_count, correlation_id=correlation_id)
        )

    graph_rebuild_queue = GraphRebuildQueue(
        graph_path=graph_path,
        get_repos=_get_repos_for_graph,
        on_queued=_on_graph_rebuild_queued,
        on_completed=_on_graph_rebuild_completed,
    )

    def _schedule_graph_rebuild(correlation_id: str | None = None) -> None:
        graph_rebuild_queue.schedule_rebuild(correlation_id=correlation_id)

    def _on_qdrant_index_then_rebuild(event: QdrantIndexCompletedEvent) -> None:
        """Qdrant 索引完成后触发依赖图重建。"""
        if event.status != "completed":
            return
        _schedule_graph_rebuild(correlation_id=event.correlation_id)

    def _on_qdrant_removed_then_rebuild(event: QdrantIndexRemovedEvent) -> None:
        """Qdrant 索引移除完成后触发依赖图重建。"""
        _schedule_graph_rebuild(correlation_id=event.correlation_id)

    resync_receiver = ResyncReceiver(
        index_queue=index_queue,
        resync_completed_event_bus=resyncCompletedEventBus,
    )
    requestResyncRepoEventBus.add_listener(resync_receiver)

    from root_seeker.events import IndexCallbackTrigger
    callback_trigger = IndexCallbackTrigger()
    qdrantIndexEventBus.add_listener(callback_trigger)
    zoektIndexEventBus.add_listener(callback_trigger)
    qdrantIndexRemovedEventBus.add_listener(callback_trigger)
    zoektIndexRemovedEventBus.add_listener(callback_trigger)
    resyncCompletedEventBus.add_listener(callback_trigger)
    qdrantIndexEventBus.add_listener(_on_qdrant_index_then_rebuild)
    qdrantIndexRemovedEventBus.add_listener(_on_qdrant_removed_then_rebuild)

    if qstore is not None:
        requestRemoveRepoEventBus.add_listener(
            QdrantRemoveReceiver(
                qstore=qstore,
                qdrant_index_removed_event_bus=qdrantIndexRemovedEventBus,
                index_queue=index_queue,
            )
        )
    zoekt_index_dir = data_dir / "zoekt" / "index"
    requestRemoveRepoEventBus.add_listener(
        ZoektRemoveReceiver(
            zoekt_index_dir=zoekt_index_dir,
            zoekt_index_removed_event_bus=zoektIndexRemovedEventBus,
            index_queue=index_queue,
        )
    )

    def _on_request_reset_all(event: RequestResetAllEvent) -> None:
        if qstore is None:
            return

        def _do() -> None:
            try:
                qstore.delete_collection()
                app_logger.info("[App] 已清除全部向量")
                if event.reindex:
                    for repo in repos_for_sync:
                        requestSyncRepoEventBus.emit(
                            RequestSyncRepoEvent(
                                service_name=repo.service_name,
                                task_types=["qdrant"],
                                incremental=False,
                                correlation_id=event.correlation_id,
                                callback_url=event.callback_url,
                            )
                        )
                    app_logger.info("[App] 已为 %d 个仓库入队索引", len(repos_for_sync))
            except Exception as e:
                app_logger.error("[App] 全量清除失败: %s", e, exc_info=True)

        try:
            loop = asyncio.get_running_loop()
            loop.run_in_executor(None, _do)
        except RuntimeError:
            _do()

    requestResetAllEventBus.add_listener(_on_request_reset_all)

    async def _run_resync(task) -> None:
        """RESYNC 任务：单次执行内依次完成 清除→索引→依赖图重建。"""
        import glob

        extra = task.result if isinstance(task.result, dict) else {}
        correlation_id = extra.get("correlation_id")
        service_name = task.service_name
        app_logger.info("[IndexQueue] 开始重新同步 job_id=%s service=%s", task.job_id, service_name)
        task.append_log("步骤1：清除")
        try:
            if qstore is not None:
                await asyncio.to_thread(qstore.delete_points_by_service, service_name=service_name)
            zoekt_index_dir = data_dir / "zoekt" / "index"
            if zoekt_index_dir.exists():
                for f in glob.glob(str(zoekt_index_dir / "*")):
                    p = Path(f)
                    if p.is_file() and service_name in p.name:
                        p.unlink(missing_ok=True)
            recently_indexed_zoekt.discard(service_name)
            task.append_log("步骤2：索引")
            candidates = router.route(service_name)
            if not candidates:
                raise ValueError("service_name not mapped")
            repo = candidates[0]
            async with index_semaphore:
                count = await vector_indexer.index_repo(
                    repo_local_dir=repo.local_dir,
                    service_name=service_name,
                    incremental=False,
                )
            task.append_log("步骤3：依赖图重建")
            repos = _get_repos_for_graph()
            builder = ServiceGraphBuilder()
            graph = builder.build(repos)
            save_graph(graph, graph_path)
            edge_count = len(graph.to_json())
            _on_graph_rebuild_completed(edge_count, correlation_id)
            task.result = count
            task.status = IndexTaskStatus.COMPLETED
            task.append_log("完成")
            resyncCompletedEventBus.emit(
                ResyncCompletedEvent(
                    service_name=service_name,
                    status="completed",
                    correlation_id=correlation_id,
                    indexed_chunks=count,
                    callback_url=task.callback_url,
                )
            )
        except Exception as e:
            task.status = IndexTaskStatus.FAILED
            task.error = str(e)
            task.append_log(f"失败: {e}")
            resyncCompletedEventBus.emit(
                ResyncCompletedEvent(
                    service_name=service_name,
                    status="failed",
                    correlation_id=correlation_id,
                    error=str(e),
                    callback_url=task.callback_url,
                )
            )
            raise

    index_queue.start_worker(
        run_qdrant=_run_qdrant,
        run_zoekt=_run_zoekt,
        run_remove_qdrant=_run_remove_qdrant if qstore is not None else None,
        run_remove_zoekt=_run_remove_zoekt,
        run_resync=_run_resync if (qstore is not None and vector_indexer is not None) else None,
    )
    app_logger.info("[App] 索引队列 worker 已启动（memory）")

    async def _run_full_reload(event: RequestFullReloadEvent) -> None:
        """后台执行全量重载：同步仓库，再为每个仓库发出移除与索引入队事件。"""
        service_names = event.service_names or [r.service_name for r in repos_for_sync]
        repos = [r for r in repos_for_sync if r.service_name in service_names]
        cid = event.correlation_id or new_correlation_id()
        for repo in repos:
            try:
                sync_result = await repo_mirror.sync(repo)
                repoSyncEventBus.emit(
                    RepoSyncCompletedEvent(
                        service_name=sync_result.service_name,
                        local_dir=sync_result.local_dir,
                        status=sync_result.status,
                        detail=sync_result.detail,
                        correlation_id=cid,
                        callback_url=event.callback_url,
                    )
                )
                requestRemoveRepoEventBus.emit(
                    RequestRemoveRepoEvent(
                        service_name=repo.service_name,
                        task_types=["qdrant", "zoekt"],
                        correlation_id=cid,
                        callback_url=event.callback_url,
                    )
                )
                requestSyncRepoEventBus.emit(
                    RequestSyncRepoEvent(
                        service_name=repo.service_name,
                        task_types=["qdrant"],
                        incremental=False,
                        correlation_id=cid,
                        callback_url=event.callback_url,
                    )
                )
            except Exception as e:
                app_logger.error(
                    "[App] 全量重载同步失败：%s, %s", repo.service_name, e, exc_info=True
                )
        app_logger.info("[App] 全量重载已入队，repos=%d", len(repos))

    def _on_request_full_reload(event: RequestFullReloadEvent) -> None:
        try:
            loop = asyncio.get_running_loop()
            asyncio.run_coroutine_threadsafe(_run_full_reload(event), loop)
        except RuntimeError:
            asyncio.run(_run_full_reload(event))

    requestFullReloadEventBus.add_listener(_on_request_full_reload)

    periodic_task_service = PeriodicTaskService(
        cfg=PeriodicTaskConfig(
            periodic_tasks_enabled=cfg.periodic_tasks_enabled,
            auto_sync_enabled=cfg.auto_sync_enabled,
            auto_sync_interval_seconds=cfg.auto_sync_interval_seconds,
            auto_index_enabled=cfg.auto_index_enabled,
            auto_index_after_sync=cfg.auto_index_after_sync,
            auto_index_interval_seconds=cfg.auto_index_interval_seconds,
            auto_sync_concurrency=cfg.auto_sync_concurrency,
            auto_index_concurrency=cfg.auto_index_concurrency,
        ),
        repos=repos_for_sync,
        repo_mirror=repo_mirror,
        vector_indexer=vector_indexer,
        index_semaphore=index_semaphore,
        index_queue=index_queue,
        on_repos_updated=_schedule_graph_rebuild,
        on_repo_sync_completed=lambda r, cid: repoSyncEventBus.emit(
            RepoSyncCompletedEvent(
                service_name=r.service_name,
                local_dir=r.local_dir,
                status=r.status,
                detail=r.detail,
                correlation_id=cid,
            )
        ),
        on_qdrant_index_completed=lambda sn, local_dir, count, cid: qdrantIndexEventBus.emit(
            QdrantIndexCompletedEvent(
                service_name=sn,
                repo_local_dir=local_dir,
                indexed_chunks=count,
                status="completed",
                correlation_id=cid,
            )
        ),
    )

    def _enqueue_ingest_event(event: IngestEvent) -> str:
        """将 IngestEvent 入队分析，返回 analysis_id。"""
        norm = to_normalized_event(event)
        analysis_id = uuid.uuid4().hex
        job_queue.enqueue(Job(analysis_id=analysis_id, event=norm))
        return analysis_id

    @app.post("/ingest")
    async def ingest_log(
        event: IngestEvent, _: None = Depends(require_api_key)
    ) -> dict[str, str]:
        """通用 JSON 日志摄入接口，接收标准格式：service_name、error_log、query_key、timestamp、tags。"""
        app_logger.info(f"[App] 收到日志摄入请求（/ingest），service={event.service_name}, query_key={event.query_key}")
        analysis_id = _enqueue_ingest_event(event)
        app_logger.info(f"[App] 任务已入队，analysis_id={analysis_id}")
        return {"status": "accepted", "analysis_id": analysis_id}

    @app.post("/ingest/aliyun-sls")
    async def ingest_aliyun_sls(
        request: Request, _: None = Depends(require_api_key)
    ) -> dict[str, str]:
        """
        阿里云 SLS 日志摄入接口。
        支持两种格式：
        1) 标准 JSON（同 /ingest）：service_name、error_log、query_key、timestamp、tags
        2) SLS 原始格式：content、__time__、__tag__ 等，将解析后转发
        """
        try:
            body = await request.json()
        except Exception as e:
            raise HTTPException(status_code=400, detail=f"Invalid JSON body: {e}") from e
        event = parse_ingest_body(body)
        if event is None:
            raise HTTPException(
                status_code=400,
                detail="Unrecognized format: need service_name+error_log (standard) or content+__time__ (SLS raw)",
            )
        app_logger.info(f"[App] 收到日志摄入请求（/ingest/aliyun-sls），service={event.service_name}, query_key={event.query_key}")
        analysis_id = _enqueue_ingest_event(event)
        app_logger.info(f"[App] 任务已入队，analysis_id={analysis_id}")
        return {"status": "accepted", "analysis_id": analysis_id}

    @app.post("/ingest/batch-cluster")
    async def ingest_batch_cluster(
        request: Request, _: None = Depends(require_api_key)
    ) -> dict:
        """
        批量日志聚类接口：接收一组日志 JSON 列表（可来自多服务），
        使用算法（指纹 + 可选 embedding）将相似问题分组，每组抽样一条进行分析。
        尽量少用 AI，仅 embedding 为本地模型，不调用 LLM。
        """
        try:
            body = await request.json()
        except Exception as e:
            raise HTTPException(status_code=400, detail=f"Invalid JSON body: {e}") from e
        if isinstance(body, list):
            logs = body
            submit_for_analysis = True
        elif isinstance(body, dict):
            logs = body.get("logs", [])
            submit_for_analysis = body.get("submit_for_analysis", True)
        else:
            raise HTTPException(status_code=400, detail="Body must be JSON array or object with 'logs' key")
        if not isinstance(logs, list):
            raise HTTPException(status_code=400, detail="logs must be a JSON array")
        if len(logs) > 5000:
            raise HTTPException(status_code=400, detail="logs count exceeds limit 5000")

        events = parse_log_list(logs)
        if not events:
            raise HTTPException(
                status_code=400,
                detail="No valid logs parsed. Each item needs service_name+error_log (standard) or content+__time__ (SLS)",
            )

        result = await log_clusterer.cluster(events)
        app_logger.info(
            f"[App] 批量聚类完成，total={len(events)}, clusters={len(result.clusters)}, method={result.method}"
        )

        clusters_info = [
            {
                "size": len(c),
                "representative_index": result.representatives[i],
                "service_name": events[result.representatives[i]].service_name,
            }
            for i, c in enumerate(result.clusters)
        ]

        analysis_ids: list[str] = []
        if submit_for_analysis:
            for idx in result.representatives:
                ev = result.events[idx]
                aid = _enqueue_ingest_event(ev)
                analysis_ids.append(aid)
            app_logger.info(f"[App] 已提交 {len(analysis_ids)} 个代表样本进行分析")

        return {
            "status": "ok",
            "total_logs": len(events),
            "total_clusters": len(result.clusters),
            "clustering_method": result.method,
            "clusters": clusters_info,
            "analysis_ids": analysis_ids if submit_for_analysis else [],
        }

    if git_source_service:
        # 统一接口：不区分底层平台（Gitee/GitHub/Codeup），配置一次后使用同一套 API

        @app.post("/git-source/verify")
        async def git_source_verify(
            request: Request, _: None = Depends(require_api_key)
        ) -> dict:
            """验证凭证是否有效（不保存）。拉取前可先调用此接口探测账号密码是否正确。"""
            try:
                body = await request.json()
            except Exception as e:
                raise HTTPException(status_code=400, detail=f"Invalid JSON: {e}") from e
            domain = body.get("domain") or body.get("domain_name")
            username = body.get("username")
            password = body.get("password")
            if not domain or not username or not password:
                raise HTTPException(status_code=400, detail="需要 domain, username, password")
            ok, msg = git_source_service.verify_credentials(
                domain=str(domain),
                username=str(username),
                password=str(password),
                platform=body.get("platform"),
                clone_protocol="https",
            )
            return {"status": "ok" if ok else "error", "message": msg}

        @app.put("/git-source/config")
        async def git_source_save_config(
            request: Request, _: None = Depends(require_api_key)
        ) -> dict:
            """保存平台凭证（一次性配置）。支持 Gitee/GitHub/GitLab/Codeup，保存后自动拉取仓库列表。"""
            try:
                body = await request.json()
            except Exception as e:
                raise HTTPException(status_code=400, detail=f"Invalid JSON: {e}") from e
            domain = body.get("domain") or body.get("domain_name")
            username = body.get("username")
            password = body.get("password")
            if not domain or not username or not password:
                raise HTTPException(status_code=400, detail="需要 domain, username, password")
            try:
                repos = git_source_service.connect(
                    domain=str(domain),
                    username=str(username),
                    password=str(password),
                    platform=body.get("platform"),
                    clone_protocol="https",
                )
            except Exception as e:
                app_logger.warning(f"[GitSource] 配置保存失败: {e}")
                raise HTTPException(status_code=400, detail=str(e)) from e
            return {
                "status": "ok",
                "message": "配置已保存，仓库列表已更新",
                "total": len(repos),
                "repos": [
                    {
                        "id": r.id,
                        "full_name": r.full_name,
                        "full_path": r.full_path,
                        "platform_id": r.platform_id,
                        "git_url": r.git_url,
                        "default_branch": r.default_branch,
                    }
                    for r in repos
                ],
            }

        @app.get("/git-source/repos")
        async def git_source_list_repos(
            search: str | None = None,
            enabled_only: bool = False,
            _: None = Depends(require_api_key),
        ) -> dict:
            """获取仓库列表（统一接口，不区分平台）。"""
            repos = git_source_service.list_repos(search=search, enabled_only=enabled_only)
            return {
                "status": "ok",
                "total": len(repos),
                "repos": [
                    {
                        "id": r.id,
                        "full_name": r.full_name,
                        "full_path": r.full_path,
                        "platform_id": r.platform_id,
                        "git_url": r.git_url,
                        "default_branch": r.default_branch,
                        "enabled": r.enabled,
                        "selected_branches": r.selected_branches,
                        "local_dir": r.local_dir,
                    }
                    for r in repos
                ],
            }

        def _validate_repo_id(rid: str) -> str:
            rid = rid.replace("%2F", "/")
            if not rid or len(rid) > 200:
                raise HTTPException(status_code=400, detail="Invalid repo_id: empty or too long")
            if ".." in rid or "\\" in rid or "\0" in rid:
                raise HTTPException(status_code=400, detail="Invalid repo_id: path traversal not allowed")
            if not all(c.isalnum() or c in "/-_." for c in rid):
                raise HTTPException(status_code=400, detail="Invalid repo_id: invalid characters")
            return rid

        @app.get("/git-source/repos/{repo_id}")
        async def git_source_get_repo(
            repo_id: str,
            branch_search: str | None = None,
            _: None = Depends(require_api_key),
        ) -> dict:
            """获取仓库详情（含分支列表）。repo_id 可为 id 或 full_name。"""
            repo_id = _validate_repo_id(repo_id)
            repos = git_source_service.list_repos()
            repo = next((r for r in repos if r.id == repo_id or r.full_path == repo_id or r.full_name == repo_id), None)
            if not repo:
                raise HTTPException(status_code=404, detail="repo not found")
            try:
                branches = git_source_service.list_branches(repo.full_path, search=branch_search)
            except ValueError as e:
                raise HTTPException(status_code=400, detail=str(e)) from e
            return {
                "status": "ok",
                "repo": {
                    "id": repo.id,
                    "full_name": repo.full_name,
                    "full_path": repo.full_path,
                    "platform_id": repo.platform_id,
                    "git_url": repo.git_url,
                    "default_branch": repo.default_branch,
                    "enabled": repo.enabled,
                    "selected_branches": repo.selected_branches,
                    "local_dir": repo.local_dir,
                },
                "branches": [{"name": b.get("name"), "protected": b.get("protected")} for b in branches],
            }

        @app.put("/git-source/repos/{repo_id}")
        async def git_source_configure_repo(
            repo_id: str,
            request: Request,
            _: None = Depends(require_api_key),
        ) -> dict:
            """配置仓库到分析工具：启用并选择分支，同步后参与根因分析。新增/修改后默认立刻同步。"""
            try:
                body = await request.json()
            except Exception as e:
                raise HTTPException(status_code=400, detail=f"Invalid JSON: {e}") from e
            branches = body.get("branches", [])
            enabled = body.get("enabled", True)
            callback_url = body.get("callback_url")
            cb = str(callback_url).strip() if callback_url and str(callback_url).strip() else None
            repo_id = _validate_repo_id(repo_id)
            updated = git_source_service.select_branches(repo_id, branches=branches, enabled=enabled)
            if not updated:
                raise HTTPException(status_code=404, detail="repo not found")
            new_repos = _dedup_repos(list(cfg.repos) + git_source_service.get_enabled_repos_as_config())
            router.refresh_catalog(new_repos)
            app_logger.info(f"[App] 仓库启用状态变更，已刷新 catalog，共 {len(new_repos)} 个仓库")
            sync_result = None
            if updated.enabled and updated.local_dir:
                repo_config = next(
                    (r for r in git_source_service.get_enabled_repos_as_config() if r.service_name == updated.service_name),
                    None,
                )
                if repo_config:
                    try:
                        sync_result = await repo_mirror.sync(repo_config)
                    except Exception as e:
                        sync_result = RepoSyncResult(
                            service_name=repo_config.service_name,
                            local_dir=repo_config.local_dir,
                            status="error",
                            detail=str(e),
                        )
            msg = "已加入分析工具"
            if sync_result:
                msg = "已加入分析工具，已同步" if sync_result.status not in ("error",) else "已加入分析工具，同步失败"
                cid = new_correlation_id()
                repoSyncEventBus.emit(
                    RepoSyncCompletedEvent(
                        service_name=sync_result.service_name,
                        local_dir=sync_result.local_dir,
                        status=sync_result.status,
                        detail=sync_result.detail,
                        correlation_id=cid,
                        callback_url=cb,
                    )
                )
                if sync_result.status not in ("error",):
                    _schedule_graph_rebuild(cid)
            return {
                "status": "ok",
                "message": msg,
                "repo": {
                    "id": updated.id,
                    "full_name": updated.full_name,
                    "full_path": updated.full_path,
                    "platform_id": updated.platform_id,
                    "enabled": updated.enabled,
                    "selected_branches": updated.selected_branches,
                    "local_dir": updated.local_dir,
                },
                "sync": {"status": sync_result.status, "detail": sync_result.detail} if sync_result else None,
            }

        @app.post("/git-source/sync")
        async def git_source_sync(
            callback_url: str | None = None,
            _: None = Depends(require_api_key),
        ) -> dict:
            """同步已配置仓库到本地，供分析使用。callback_url 可选。"""
            cb = callback_url.strip() if callback_url and callback_url.strip() else None
            git_repos = git_source_service.get_enabled_repos_as_config()
            if not git_repos:
                return {"status": "ok", "message": "无已配置的仓库", "results": []}
            cid = new_correlation_id()
            sem = asyncio.Semaphore(8)

            async def _sync_one(repo):
                async with sem:
                    return await repo_mirror.sync(repo)

            results = []
            for r in await asyncio.gather(*[_sync_one(repo) for repo in git_repos], return_exceptions=True):
                if isinstance(r, Exception):
                    results.append({"status": "error", "detail": str(r)})
                else:
                    results.append({"service_name": r.service_name, "status": r.status, "detail": r.detail})
                    repoSyncEventBus.emit(
                        RepoSyncCompletedEvent(
                            service_name=r.service_name,
                            local_dir=r.local_dir,
                            status=r.status,
                            detail=r.detail,
                            correlation_id=cid,
                            callback_url=cb,
                        )
                    )
            success_count = sum(1 for x in results if isinstance(x, dict) and x.get("status") in ("updated", "cloned"))
            if success_count > 0:
                _schedule_graph_rebuild(cid)
            return {"status": "ok", "results": results}

        @app.post("/git-source/notify")
        async def git_source_notify(_: None = Depends(require_api_key)) -> dict:
            """仓库配置变更通知：若依等管理端在拉取/编辑/同步仓库后调用，RootSeeker 刷新 catalog。"""
            git_repos = git_source_service.get_enabled_repos_as_config()
            new_repos = _dedup_repos(list(cfg.repos) + git_repos)
            router.refresh_catalog(new_repos)
            app_logger.info(f"[App] 收到仓库变更通知，已刷新 catalog，共 {len(new_repos)} 个仓库")
            return {"status": "ok", "message": "catalog refreshed", "repo_count": len(new_repos)}

    # 应用配置 API（数据库模式，供若依管理端使用）
    config_db = get_config_db()
    if config_db:

        @app.get("/app-config")
        async def app_config_list(_: None = Depends(require_api_key)) -> dict:
            """列出所有配置分类及当前有效配置。"""
            from root_seeker.config_db import load_config_from_db

            db_cfg = load_config_from_db(
                host=config_db.get("host", "localhost"),
                port=int(config_db.get("port", 3306)),
                user=config_db.get("user", "root"),
                password=config_db.get("password", ""),
                database=config_db.get("database", "root_seeker"),
            )
            return {"status": "ok", "config": db_cfg}

        @app.get("/app-config/system")
        async def app_config_system(_: None = Depends(require_api_key)) -> dict:
            """获取系统配置（config_source 等）。"""
            from root_seeker.config_db import get_config_source_from_db

            src = get_config_source_from_db(
                host=config_db.get("host", "localhost"),
                port=int(config_db.get("port", 3306)),
                user=config_db.get("user", "root"),
                password=config_db.get("password", ""),
                database=config_db.get("database", "root_seeker"),
            )
            return {"status": "ok", "config_source": src}

        @app.put("/app-config/system")
        async def app_config_system_save(
            request: Request, _: None = Depends(require_api_key)
        ) -> dict:
            """设置系统配置（config_source）。"""
            try:
                body = await request.json()
            except Exception:
                raise HTTPException(status_code=400, detail="Invalid JSON")
            source = (body.get("config_source") or "file").strip().lower()
            if source not in ("file", "database"):
                raise HTTPException(status_code=400, detail="config_source must be file or database")
            from root_seeker.config_db import set_config_source_in_db

            set_config_source_in_db(
                host=config_db.get("host", "localhost"),
                port=int(config_db.get("port", 3306)),
                user=config_db.get("user", "root"),
                password=config_db.get("password", ""),
                database=config_db.get("database", "root_seeker"),
                source=source,
            )
            return {"status": "ok", "config_source": source}

        @app.get("/app-config/{category}")
        async def app_config_get(
            category: str, _: None = Depends(require_api_key)
        ) -> dict:
            """获取指定分类的配置。"""
            if not category or not all(c.isalnum() or c in "_-" for c in category):
                raise HTTPException(status_code=400, detail="Invalid category")
            from root_seeker.config_db import load_config_from_db

            db_cfg = load_config_from_db(
                host=config_db.get("host", "localhost"),
                port=int(config_db.get("port", 3306)),
                user=config_db.get("user", "root"),
                password=config_db.get("password", ""),
                database=config_db.get("database", "root_seeker"),
            )
            val = db_cfg.get(category)
            return {"status": "ok", "category": category, "config": val}

        @app.put("/app-config/{category}")
        async def app_config_save(
            category: str, request: Request, _: None = Depends(require_api_key)
        ) -> dict:
            """保存指定分类的配置。"""
            if not category or not all(c.isalnum() or c in "_-" for c in category):
                raise HTTPException(status_code=400, detail="Invalid category")
            if category == "system":
                raise HTTPException(status_code=400, detail="Use PUT /app-config/system for system config")
            try:
                body = await request.json()
            except Exception:
                raise HTTPException(status_code=400, detail="Invalid JSON")
            from root_seeker.config_db import save_config_to_db

            save_config_to_db(
                host=config_db.get("host", "localhost"),
                port=int(config_db.get("port", 3306)),
                user=config_db.get("user", "root"),
                password=config_db.get("password", ""),
                database=config_db.get("database", "root_seeker"),
                config_category=category,
                config_value=body,
            )
            return {"status": "ok", "category": category}

        @app.post("/app-config/notify")
        async def app_config_notify(_: None = Depends(require_api_key)) -> dict:
            """配置变更通知：若依等管理端保存配置后调用。
            LLM/Embedding 等配置在启动时加载，修改后需重启 RootSeeker 容器才能生效。"""
            app_logger.info(
                "[App] 收到配置变更通知（LLM/Embedding 等需重启 RootSeeker 容器后生效）"
            )
            return {
                "status": "ok",
                "message": "config change notified",
                "restart_required": "LLM/Embedding 等配置需重启 RootSeeker 容器后生效",
            }

    @app.get("/analysis/{analysis_id}")
    async def get_analysis(analysis_id: str, _: None = Depends(require_api_key)) -> dict:
        # 安全验证：确保 analysis_id 格式正确
        if not analysis_id or len(analysis_id) > 64 or not all(c.isalnum() or c in "-_" for c in analysis_id):
            raise HTTPException(status_code=400, detail="Invalid analysis_id format")
        app_logger.debug(f"[App] 查询分析结果，analysis_id={analysis_id}")
        try:
            report = store.load(analysis_id)
        except ValueError as e:
            raise HTTPException(status_code=400, detail=str(e))
        if report is not None:
            app_logger.debug(f"[App] 返回分析报告，analysis_id={analysis_id}, status=completed")
            return report.model_dump()
        try:
            status = status_store.load(analysis_id)
        except ValueError as e:
            raise HTTPException(status_code=400, detail=str(e))
        if status is None:
            app_logger.warning(f"[App] 分析ID不存在，analysis_id={analysis_id}")
            raise HTTPException(status_code=404, detail="analysis_id not found")
        app_logger.debug(f"[App] 返回分析状态，analysis_id={analysis_id}, status={status.status}")
        out = status.model_dump(mode="json")
        out["status_display"] = {"pending": "待调度", "running": "解析中", "completed": "解析完成", "failed": "解析失败"}.get(status.status, status.status)
        return out

    def _list_zoekt_indexed_from_disk(zoekt_index_dir: Path) -> set[str]:
        """从索引目录扫描 .zoekt 文件获取已索引仓库名（/api/list 不可用时的回退）。"""
        import re
        names: set[str] = set()
        if not zoekt_index_dir.exists():
            return names
        for f in zoekt_index_dir.iterdir():
            if f.is_file() and f.suffix == ".zoekt" and "_v" in f.stem:
                # 格式: repo_name_v16.00000.zoekt -> repo_name
                m = re.match(r"^(.+)_v\d+\.\d+$", f.stem)
                if m:
                    names.add(m.group(1))
        return names

    @app.get("/index/status")
    async def get_index_status(_: None = Depends(require_api_key)) -> dict[str, Any]:
        """
        返回各仓库的 Qdrant 与 Zoekt 索引状态。
        每项含：service_name, qdrant_indexed, qdrant_indexing, qdrant_count, zoekt_indexed, zoekt_indexing。
        使用 router catalog（notify 后已刷新），确保新启用的仓库能立即显示。
        """
        zoekt_repos: set[str] | None = None
        if zoekt is not None:
            zoekt_repos = await zoekt.list_indexed_repos()
        zoekt_index_dir = data_dir / "zoekt" / "index"
        if zoekt_repos is None and zoekt_index_dir.exists():
            zoekt_repos = _list_zoekt_indexed_from_disk(zoekt_index_dir)
        def _status_rank(s: str | None) -> int:
            order = {"清理中": 3, "索引中": 2, "已索引": 1, "未索引": 0, "未知": -1}
            return order.get(s or "未知", -1)

        merged: dict[str, dict[str, Any]] = {}
        current_repos = router._catalog.repos
        for repo in current_repos:
            sn = repo.service_name
            zoekt_name_candidates = {sn, Path(repo.local_dir).name}
            qdrant_count: int | None = 0
            qdrant_count_unknown = False
            if qstore is not None:
                try:
                    qdrant_count = await asyncio.wait_for(
                        asyncio.to_thread(qstore.count_points_by_service, service_name=sn),
                        timeout=15.0,
                    )
                except (asyncio.TimeoutError, Exception) as e:
                    app_logger.debug(f"[App] Qdrant count 超时/异常，service={sn}: {e}")
                    qdrant_count = None
            if qdrant_count is None:
                qdrant_count_unknown = True
            qdrant_task = index_queue.get_task_by_service(sn, IndexTaskType.QDRANT) if index_queue else None
            zoekt_task = index_queue.get_task_by_service(sn, IndexTaskType.ZOEKT) if index_queue else None
            qdrant_remove_task = index_queue.get_task_by_service(sn, IndexTaskType.REMOVE_QDRANT) if index_queue else None
            zoekt_remove_task = index_queue.get_task_by_service(sn, IndexTaskType.REMOVE_ZOEKT) if index_queue else None
            qdrant_indexing = (qdrant_task is not None and qdrant_task.status in (IndexTaskStatus.QUEUED, IndexTaskStatus.RUNNING)) or (sn in indexing_qdrant)
            zoekt_indexing = zoekt_task is not None and zoekt_task.status in (IndexTaskStatus.QUEUED, IndexTaskStatus.RUNNING)
            qdrant_removing = qdrant_remove_task is not None and qdrant_remove_task.status in (IndexTaskStatus.QUEUED, IndexTaskStatus.RUNNING)
            zoekt_removing = zoekt_remove_task is not None and zoekt_remove_task.status in (IndexTaskStatus.QUEUED, IndexTaskStatus.RUNNING)
            qdrant_indexed: bool | None
            if qdrant_count_unknown:
                qdrant_indexed = True if (qdrant_task and qdrant_task.status == IndexTaskStatus.COMPLETED) else None
            else:
                qdrant_indexed = (qdrant_count or 0) > 0
            zoekt_indexed_val = (
                bool(zoekt_name_candidates & (zoekt_repos or set()))
                or (sn in recently_indexed_zoekt)
                or (zoekt_task is not None and zoekt_task.status == IndexTaskStatus.COMPLETED)
                if (zoekt_repos is not None or recently_indexed_zoekt or (zoekt_task and zoekt_task.status == IndexTaskStatus.COMPLETED))
                else None
            )
            # 单字段状态：未索引|索引中|已索引|清理中
            if qdrant_removing:
                _qdrant_status = "清理中"
            elif qdrant_indexing:
                _qdrant_status = "索引中"
            elif qdrant_indexed is None:
                _qdrant_status = "未知"
            else:
                _qdrant_status = "已索引" if qdrant_indexed else "未索引"

            if zoekt_removing:
                _zoekt_status = "清理中"
            elif zoekt_indexing:
                _zoekt_status = "索引中"
            elif zoekt_indexed_val is None:
                _zoekt_status = "未知"
            else:
                _zoekt_status = "已索引" if zoekt_indexed_val else "未索引"
            item: dict[str, Any] = {
                "service_name": sn,
                "qdrant_status": _qdrant_status,
                "qdrant_indexed": qdrant_indexed,
                "qdrant_indexing": qdrant_indexing,
                "qdrant_removing": qdrant_removing,
                "qdrant_count": qdrant_count,
                "qdrant_job_id": qdrant_task.job_id if qdrant_task else None,
                "zoekt_status": _zoekt_status,
                "zoekt_indexed": zoekt_indexed_val,
                "zoekt_indexing": zoekt_indexing,
                "zoekt_removing": zoekt_removing,
                "zoekt_job_id": zoekt_task.job_id if zoekt_task else None,
            }
            prev = merged.get(sn)
            if prev is None:
                merged[sn] = item
                continue
            if _status_rank(item.get("qdrant_status")) > _status_rank(prev.get("qdrant_status")):
                prev["qdrant_status"] = item.get("qdrant_status")
            if item.get("qdrant_count") is not None:
                prev_count = prev.get("qdrant_count")
                if prev_count is None or item["qdrant_count"] > prev_count:
                    prev["qdrant_count"] = item["qdrant_count"]
            if prev.get("qdrant_indexed") is None:
                prev["qdrant_indexed"] = item.get("qdrant_indexed")
            prev["qdrant_indexing"] = bool(prev.get("qdrant_indexing")) or bool(item.get("qdrant_indexing"))
            prev["qdrant_removing"] = bool(prev.get("qdrant_removing")) or bool(item.get("qdrant_removing"))
            prev["qdrant_job_id"] = prev.get("qdrant_job_id") or item.get("qdrant_job_id")

            if _status_rank(item.get("zoekt_status")) > _status_rank(prev.get("zoekt_status")):
                prev["zoekt_status"] = item.get("zoekt_status")
            if prev.get("zoekt_indexed") is None:
                prev["zoekt_indexed"] = item.get("zoekt_indexed")
            prev["zoekt_indexing"] = bool(prev.get("zoekt_indexing")) or bool(item.get("zoekt_indexing"))
            prev["zoekt_removing"] = bool(prev.get("zoekt_removing")) or bool(item.get("zoekt_removing"))
            prev["zoekt_job_id"] = prev.get("zoekt_job_id") or item.get("zoekt_job_id")

        return {"repos": list(merged.values())}

    @app.post("/index/repo/{service_name}")
    async def index_repo(
        service_name: str,
        incremental: bool = False,
        callback_url: str | None = None,
        _: None = Depends(require_api_key),
    ) -> dict[str, Any]:
        """
        为指定仓库建向量索引。使用队列时立即返回 job_id，任务在后台执行。
        incremental=true：仅索引 git pull 后的变更文件（需 ORIG_HEAD 有效），否则全量。
        callback_url：任务完成后 POST 回调，用于 Admin 更新 repo_index_status。
        """
        if not service_name or len(service_name) > 100 or not all(c.isalnum() or c in "-_./" for c in service_name):
            raise HTTPException(status_code=400, detail="Invalid service_name format")
        app_logger.info(f"[App] 收到仓库索引请求，service={service_name}, incremental={incremental}")
        if vector_indexer is None:
            raise HTTPException(status_code=400, detail="vector indexing is not configured")
        candidates = router.route(service_name)
        if not candidates:
            raise HTTPException(status_code=404, detail="service_name not mapped to any repo")
        cid = new_correlation_id()
        req_event = RequestSyncRepoEvent(
            service_name=service_name,
            task_types=["qdrant"],
            incremental=incremental,
            correlation_id=cid,
            callback_url=callback_url.strip() if callback_url and callback_url.strip() else None,
        )
        requestSyncRepoEventBus.emit(req_event)
        if index_queue is not None:
            job_id = req_event.result.get("qdrant_job_id")
            if job_id:
                return {"status": "queued", "job_id": job_id, "message": "任务已入队，正在排队执行"}
        repo = candidates[0]
        cb = req_event.callback_url
        try:
            count = await vector_indexer.index_repo(
                repo_local_dir=repo.local_dir,
                service_name=service_name,
                incremental=incremental,
            )
            qdrantIndexEventBus.emit(
                QdrantIndexCompletedEvent(
                    service_name=service_name,
                    repo_local_dir=repo.local_dir,
                    indexed_chunks=count,
                    status="completed",
                    correlation_id=cid,
                    callback_url=cb,
                )
            )
            return {"status": "ok", "indexed_chunks": count}
        except Exception as e:
            qdrantIndexEventBus.emit(
                QdrantIndexCompletedEvent(
                    service_name=service_name,
                    repo_local_dir=repo.local_dir,
                    indexed_chunks=0,
                    status="failed",
                    error=str(e),
                    correlation_id=cid,
                    callback_url=cb,
                )
            )
            app_logger.error(f"[App] 仓库索引失败，service={service_name}, 错误={e}", exc_info=True)
            raise HTTPException(status_code=500, detail=f"index_repo failed: {e!s}")

    @app.post("/index/zoekt/{service_name}")
    async def index_zoekt_repo(
        service_name: str,
        callback_url: str | None = None,
        _: None = Depends(require_api_key),
    ) -> dict[str, Any]:
        """为指定仓库建 Zoekt 索引。使用队列时立即返回 job_id，任务在后台执行。callback_url 可选。"""
        if not service_name or len(service_name) > 100 or not all(c.isalnum() or c in "-_./" for c in service_name):
            raise HTTPException(status_code=400, detail="Invalid service_name format")
        candidates = router.route(service_name)
        if not candidates:
            raise HTTPException(status_code=404, detail="service_name not mapped to any repo")
        cid = new_correlation_id()
        req_event = RequestSyncRepoEvent(
            service_name=service_name,
            task_types=["zoekt"],
            correlation_id=cid,
            callback_url=callback_url.strip() if callback_url and callback_url.strip() else None,
        )
        requestSyncRepoEventBus.emit(req_event)
        if index_queue is not None:
            job_id = req_event.result.get("zoekt_job_id")
            if job_id:
                return {"status": "queued", "job_id": job_id, "message": "任务已入队，正在排队执行"}
        # 无队列时同步执行（兼容）
        cb = req_event.callback_url
        repo = candidates[0]
        import shutil
        import tempfile
        zoekt_index = shutil.which("zoekt-index")
        if not zoekt_index:
            gobin = os.environ.get("GOPATH", "")
            if gobin:
                cand = Path(gobin) / "bin" / "zoekt-index"
                if cand.exists():
                    zoekt_index = str(cand)
            if not zoekt_index:
                for base in (Path.home() / "go", Path("/usr/local/go")):
                    cand = base / "bin" / "zoekt-index"
                    if cand.exists():
                        zoekt_index = str(cand)
                        break
            if not zoekt_index or not Path(zoekt_index).exists():
                raise HTTPException(
                    status_code=400,
                    detail="zoekt-index 未找到，请执行: go install github.com/google/zoekt/cmd/zoekt-index@latest",
                )
        index_dir = data_dir / "zoekt" / "index"
        index_dir.mkdir(parents=True, exist_ok=True)
        tmpdir_cleanup: Path | None = None
        try:
            index_target = Path(repo.local_dir).resolve()
            if index_target.name != service_name:
                tmpdir_cleanup = Path(tempfile.mkdtemp(prefix="zoekt-index-"))
                link_path = tmpdir_cleanup / service_name
                link_path.symlink_to(index_target)
                index_target = link_path
            proc = await asyncio.create_subprocess_exec(
                zoekt_index, "-index", str(index_dir), str(index_target),
                stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE,
            )
            stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=600)
            if proc.returncode != 0:
                err = (stderr or stdout or b"").decode("utf-8", errors="replace").strip()
                zoektIndexEventBus.emit(
                    ZoektIndexCompletedEvent(
                        service_name=service_name,
                        repo_local_dir=repo.local_dir,
                        status="failed",
                        error=err,
                        correlation_id=cid,
                        callback_url=cb,
                    )
                )
                raise HTTPException(status_code=500, detail=f"zoekt-index failed: {err}")
            recently_indexed_zoekt.add(service_name)
            zoektIndexEventBus.emit(
                ZoektIndexCompletedEvent(
                    service_name=service_name,
                    repo_local_dir=repo.local_dir,
                    status="completed",
                    correlation_id=cid,
                    callback_url=cb,
                )
            )
            return {"status": "ok", "message": "Zoekt 索引完成"}
        except asyncio.TimeoutError:
            zoektIndexEventBus.emit(
                ZoektIndexCompletedEvent(
                    service_name=service_name,
                    repo_local_dir=repo.local_dir,
                    status="failed",
                    error="zoekt-index 超时",
                    correlation_id=cid,
                    callback_url=cb,
                )
            )
            raise HTTPException(status_code=500, detail="zoekt-index 超时")
        finally:
            if tmpdir_cleanup is not None and tmpdir_cleanup.exists():
                shutil.rmtree(tmpdir_cleanup, ignore_errors=True)

    @app.get("/index/job/{job_id}")
    async def get_index_job(
        job_id: str,
        _: None = Depends(require_api_key),
    ) -> dict[str, Any]:
        """获取索引任务详情（含日志），供 Admin 队列展示与追踪。"""
        if index_queue is None:
            raise HTTPException(status_code=400, detail="索引队列未启用")
        task = index_queue.get_task(job_id)
        if task is None:
            raise HTTPException(status_code=404, detail="任务不存在")
        return {
            "job_id": task.job_id,
            "service_name": task.service_name,
            "task_type": task.task_type.value,
            "status": task.status.value,
            "logs": task.logs,
            "result": task.result,
            "error": task.error,
            "created_at": task.created_at.isoformat() if task.created_at else None,
            "started_at": task.started_at.isoformat() if task.started_at else None,
            "finished_at": task.finished_at.isoformat() if task.finished_at else None,
        }

    @app.get("/index/queue")
    async def get_index_queue(
        _: None = Depends(require_api_key),
    ) -> dict[str, Any]:
        """获取索引队列列表（排队中、运行中、近期完成），供 Admin 队列调度展示。"""
        if index_queue is None:
            return {"jobs": [], "queue_type": "none"}
        tasks = index_queue.get_all_tasks()
        jobs = []
        for t in tasks.values():
            jobs.append({
                "job_id": t.job_id,
                "service_name": t.service_name,
                "task_type": t.task_type.value,
                "status": t.status.value,
                "created_at": t.created_at.isoformat() if t.created_at else None,
                "started_at": t.started_at.isoformat() if t.started_at else None,
                "finished_at": t.finished_at.isoformat() if t.finished_at else None,
            })
        jobs.sort(key=lambda x: (x["created_at"] or ""), reverse=True)
        return {"jobs": jobs[:100], "queue_type": "memory"}

    @app.post("/index/repo/{service_name}/reset")
    async def reset_repo_index(
        service_name: str,
        callback_url: str | None = None,
        _: None = Depends(require_api_key),
    ) -> dict[str, int | str]:
        """
        全量重置：清除该服务的向量索引，然后从头重新索引。callback_url 可选。
        """
        if not service_name or len(service_name) > 100 or not all(c.isalnum() or c in "-_./" for c in service_name):
            raise HTTPException(status_code=400, detail="Invalid service_name format")
        app_logger.info(f"[App] 收到全量重置请求，service={service_name}")
        if vector_indexer is None or qstore is None:
            app_logger.warning("[App] 向量索引未配置")
            raise HTTPException(status_code=400, detail="vector indexing is not configured")
        candidates = router.route(service_name)
        if not candidates:
            raise HTTPException(status_code=404, detail="service_name not mapped to any repo")
        repo = candidates[0]
        cb = callback_url.strip() if callback_url and callback_url.strip() else None
        cid = new_correlation_id()
        try:
            await asyncio.to_thread(qstore.delete_points_by_service, service_name=service_name)
            app_logger.info(f"[App] 已清除向量，开始重新索引：{service_name}")
            indexing_qdrant.add(service_name)
            try:
                async with index_semaphore:
                    count = await vector_indexer.index_repo(
                        repo_local_dir=repo.local_dir,
                        service_name=service_name,
                        incremental=False,
                    )
                app_logger.info(f"[App] 全量重置完成，service={service_name}, 索引块数={count}")
                qdrantIndexEventBus.emit(
                    QdrantIndexCompletedEvent(
                        service_name=service_name,
                        repo_local_dir=repo.local_dir,
                        indexed_chunks=count,
                        status="completed",
                        correlation_id=cid,
                        callback_url=cb,
                    )
                )
                return {"status": "ok", "indexed_chunks": count}
            finally:
                indexing_qdrant.discard(service_name)
        except Exception as e:
            indexing_qdrant.discard(service_name)
            qdrantIndexEventBus.emit(
                QdrantIndexCompletedEvent(
                    service_name=service_name,
                    repo_local_dir=repo.local_dir,
                    indexed_chunks=0,
                    status="failed",
                    error=str(e),
                    correlation_id=cid,
                    callback_url=cb,
                )
            )
            app_logger.error(f"[App] 全量重置失败，service={service_name}, 错误={e}", exc_info=True)
            raise HTTPException(status_code=500, detail=f"reset failed: {e!s}")

    @app.post("/index/repo/{service_name}/clear")
    async def clear_repo_index(
        service_name: str,
        callback_url: str | None = None,
        _: None = Depends(require_api_key),
    ) -> dict[str, str]:
        """仅清除该服务的 Qdrant 与 Zoekt 索引，不重索引。callback_url 可选。"""
        if not service_name or len(service_name) > 100 or not all(c.isalnum() or c in "-_./" for c in service_name):
            raise HTTPException(status_code=400, detail="Invalid service_name format")
        if qstore is None:
            raise HTTPException(status_code=400, detail="vector indexing is not configured")
        cid = new_correlation_id()
        req_event = RequestRemoveRepoEvent(
            service_name=service_name,
            task_types=["qdrant", "zoekt"],
            correlation_id=cid,
            callback_url=callback_url.strip() if callback_url and callback_url.strip() else None,
        )
        requestRemoveRepoEventBus.emit(req_event)
        recently_indexed_zoekt.discard(service_name)
        app_logger.info(f"[App] 已请求移除索引，service={service_name}")
        return {"status": "ok", "message": "cleared"}

    @app.post("/index/repo/{service_name}/resync")
    async def resync_repo_index(
        service_name: str,
        callback_url: str | None = None,
        _: None = Depends(require_api_key),
    ) -> dict[str, Any]:
        """重新同步：先清除后添加，添加完成后触发依赖图重建。callback_url 可选。"""
        if not service_name or len(service_name) > 100 or not all(c.isalnum() or c in "-_./" for c in service_name):
            raise HTTPException(status_code=400, detail="Invalid service_name format")
        if qstore is None:
            raise HTTPException(status_code=400, detail="vector indexing is not configured")
        if not router.route(service_name):
            raise HTTPException(status_code=404, detail="service_name not mapped to any repo")
        cid = new_correlation_id()
        requestResyncRepoEventBus.emit(
            RequestResyncRepoEvent(
                service_name=service_name,
                task_types=["qdrant", "zoekt"],
                correlation_id=cid,
                callback_url=callback_url.strip() if callback_url and callback_url.strip() else None,
            )
        )
        recently_indexed_zoekt.discard(service_name)
        app_logger.info(f"[App] 已请求重新同步，service={service_name}")
        return {"status": "ok", "message": "已入队处理"}

    @app.post("/index/reset-all")
    async def reset_all_index(
        reindex: bool = False,
        callback_url: str | None = None,
        _: None = Depends(require_api_key),
    ) -> dict[str, Any]:
        """
        强制清除全部向量索引。reindex=true 时清除后按仓库排队重新索引。callback_url 可选。
        """
        app_logger.info(f"[App] 收到全量清除请求，reindex={reindex}")
        if qstore is None:
            raise HTTPException(status_code=400, detail="vector indexing is not configured")
        cid = new_correlation_id()
        cb = callback_url.strip() if callback_url and callback_url.strip() else None
        requestResetAllEventBus.emit(
            RequestResetAllEvent(reindex=reindex, correlation_id=cid, callback_url=cb)
        )
        return {
            "status": "ok",
            "message": "已入队处理" if reindex else "已入队清除",
            "cleared": True,
            "indexed_chunks": 0,
        }

    @app.post("/repos/full-reload")
    async def full_reload_repos(
        service_name: str | None = None,
        callback_url: str | None = None,
        _: None = Depends(require_api_key),
    ) -> dict[str, Any]:
        """
        全量重新加载：发出事件后由接收器后台执行同步，再通过队列移除并重新索引。
        service_name、callback_url 可选。
        """
        app_logger.info(f"[App] 收到全量重载请求，service_name={service_name or 'all'}")
        if qstore is None:
            raise HTTPException(status_code=400, detail="vector indexing is not configured")
        repos_to_process = repos_for_sync
        if service_name:
            if not all(c.isalnum() or c in "-_./" for c in service_name):
                raise HTTPException(status_code=400, detail="Invalid service_name format")
            repos_to_process = [r for r in repos_for_sync if r.service_name == service_name]
            if not repos_to_process:
                raise HTTPException(status_code=404, detail="service_name not found")
        if not repos_to_process:
            return {"status": "ok", "message": "无仓库", "repos_queued": 0}
        cid = new_correlation_id()
        cb = callback_url.strip() if callback_url and callback_url.strip() else None
        requestFullReloadEventBus.emit(
            RequestFullReloadEvent(
                service_names=[r.service_name for r in repos_to_process],
                correlation_id=cid,
                callback_url=cb,
            )
        )
        return {
            "status": "ok",
            "message": "已入队处理",
            "repos_queued": len(repos_to_process),
        }

    @app.get("/graph")
    async def get_graph(_: None = Depends(require_api_key)) -> dict:
        """返回完整服务依赖图（caller -> callee 边列表），便于查看各项目依赖关系。"""
        graph = load_graph(graph_path)
        if graph is None:
            raise HTTPException(status_code=404, detail="service graph not built, call POST /graph/rebuild first")
        edges = graph.to_json()
        summary = [{"caller": e["caller"], "callee": e["callee"]} for e in edges]
        return {"edges": edges, "summary": summary, "total_edges": len(edges)}

    @app.post("/graph/rebuild")
    async def rebuild_graph(_: None = Depends(require_api_key)) -> dict[str, int | str]:
        """重建服务依赖图（含 config.repos 与 git_source 已启用仓库）。"""
        app_logger.info("[App] 开始重建服务依赖图")
        try:
            builder = ServiceGraphBuilder()
            graph = builder.build(repos_for_sync)
            save_graph(graph, graph_path)
            edge_count = len(graph.to_json())
            app_logger.info(f"[App] 服务依赖图重建完成，边数={edge_count}")
            return {"status": "ok", "edges": edge_count}
        except Exception as e:
            app_logger.error(f"[App] 服务依赖图重建失败：{e}", exc_info=True)
            raise HTTPException(status_code=500, detail=f"graph/rebuild failed: {e!s}")

    @app.get("/graph/service/{service_name}")
    async def get_service_graph(service_name: str, _: None = Depends(require_api_key)) -> dict:
        # 安全验证：确保 service_name 格式正确
        if not service_name or len(service_name) > 100 or not all(c.isalnum() or c in "-_./" for c in service_name):
            raise HTTPException(status_code=400, detail="Invalid service_name format")
        graph = load_graph(graph_path)
        if graph is None:
            raise HTTPException(status_code=404, detail="service graph not built")
        return {
            "service_name": service_name,
            "upstreams": [s.model_dump() for s in graph.upstream_of(service_name)],
            "downstreams": [s.model_dump() for s in graph.downstream_of(service_name)],
        }

    @app.get("/repos/list")
    async def list_repos(_: None = Depends(require_api_key)) -> dict[str, Any]:
        """返回仓库列表（含 config.repos 与 git_source 已启用），供异常测试等项目选择。"""
        out = [
            {"service_name": r.service_name, "local_dir": r.local_dir}
            for r in repos_for_sync
        ]
        return {"repos": out}

    @app.post("/repos/sync")
    async def sync_repos(
        service_name: str | None = None,
        callback_url: str | None = None,
        _: None = Depends(require_api_key),
    ) -> dict:
        """同步仓库（含 config.repos 与 git_source 已启用仓库）。callback_url 可选。"""
        app_logger.info(f"[App] 收到仓库同步请求，service={service_name or 'all'}")
        cb = callback_url.strip() if callback_url and callback_url.strip() else None
        all_repos = repos_for_sync
        if service_name:
            matches = [r for r in all_repos if r.service_name == service_name or service_name in r.repo_aliases]
        else:
            matches = list(all_repos)
        if not matches:
            app_logger.warning(f"[App] 未找到匹配的仓库，service={service_name}")
            raise HTTPException(status_code=404, detail="no repos matched")

        app_logger.info(f"[App] 开始同步 {len(matches)} 个仓库")
        cid = new_correlation_id()
        sem = asyncio.Semaphore(8)

        async def _one(r):
            async with sem:
                app_logger.debug(f"[App] 同步仓库：{r.service_name}")
                return (r.service_name, await repo_mirror.sync(r))

        try:
            results = await asyncio.gather(*[_one(r) for r in matches])
            out = [dataclasses.asdict(res) for _, res in results]
            success_count = len([r for _, r in results if r.status in ("updated", "cloned")])
            error_count = len([r for _, r in results if r.status == "error"])
            for _, res in results:
                repoSyncEventBus.emit(
                    RepoSyncCompletedEvent(
                        service_name=res.service_name,
                        local_dir=res.local_dir,
                        status=res.status,
                        detail=res.detail,
                        correlation_id=cid,
                        callback_url=cb,
                    )
                )
            app_logger.info(f"[App] 仓库同步完成，成功={success_count}, 失败={error_count}")
            if success_count > 0:
                _schedule_graph_rebuild(cid)
            return {"status": "ok", "repos": out}
        except Exception as e:
            app_logger.error(f"[App] 仓库同步失败：{e}", exc_info=True)
            raise HTTPException(status_code=500, detail=f"repos/sync failed: {e!s}")

    @app.get("/healthz")
    async def healthz(check_deps: bool = False) -> dict[str, Any]:
        """
        健康检查接口。

        Args:
            check_deps: 为 true 时检查依赖服务（Zoekt、Qdrant）的可达性
        """
        status = {"status": "ok"}
        if check_deps:
            deps: dict[str, str] = {}
            # 检查 Zoekt
            if zoekt is not None:
                try:
                    # 尝试一个简单查询
                    await asyncio.wait_for(zoekt.search(query="test"), timeout=2.0)
                    deps["zoekt"] = "ok"
                except Exception as e:
                    deps["zoekt"] = f"error: {type(e).__name__}"
            else:
                deps["zoekt"] = "not_configured"
            # 检查 Qdrant
            if qstore is not None and cfg.qdrant is not None:
                try:
                    # 尝试获取 collections
                    import httpx
                    async with httpx.AsyncClient(timeout=2.0) as client:
                        resp = await client.get(f"{cfg.qdrant.url}/collections")
                        if resp.status_code == 200:
                            deps["qdrant"] = "ok"
                        else:
                            deps["qdrant"] = f"error: status {resp.status_code}"
                except Exception as e:
                    deps["qdrant"] = f"error: {type(e).__name__}"
            else:
                deps["qdrant"] = "not_configured"
            status["dependencies"] = deps
        return status

    app.state.event_bus = event_bus
    app.state.repo_sync_event_bus = repoSyncEventBus
    app.state.qdrant_index_event_bus = qdrantIndexEventBus
    app.state.graph_rebuild_event_bus = graphRebuildEventBus
    app.state.repo_index_sync_event_bus = repoIndexSyncEventBus
    app.state.request_sync_repo_event_bus = requestSyncRepoEventBus
    app.state.request_remove_repo_event_bus = requestRemoveRepoEventBus
    app.state.qdrant_index_removed_event_bus = qdrantIndexRemovedEventBus
    app.state.zoekt_index_removed_event_bus = zoektIndexRemovedEventBus
    app.state.zoekt_index_event_bus = zoektIndexEventBus
    app.state.graph_rebuild_completed_event_bus = graphRebuildCompletedEventBus
    app.state.request_reset_all_event_bus = requestResetAllEventBus
    app.state.request_full_reload_event_bus = requestFullReloadEventBus
    app.state.request_resync_repo_event_bus = requestResyncRepoEventBus
    app.state.resync_completed_event_bus = resyncCompletedEventBus

    @app.on_event("startup")
    async def _startup() -> None:
        app_logger.info("[App] 应用启动中...")
        await graph_rebuild_queue.start()
        await job_queue.start()
        await periodic_task_service.start()
        app_logger.info("[App] 应用启动完成")

    @app.on_event("shutdown")
    async def _shutdown() -> None:
        app_logger.info("[App] 应用关闭中...")
        if index_queue is not None:
            index_queue.stop_worker()
        await periodic_task_service.stop()
        await graph_rebuild_queue.shutdown()
        await job_queue.shutdown()
        tasks = []
        if zoekt is not None:
            tasks.append(zoekt.aclose())
        if llm_client_to_close is not None:
            tasks.append(llm_client_to_close.aclose())
        # 关闭所有 notifiers 的客户端连接
        for notifier in notifiers:
            if hasattr(notifier, "_client"):
                tasks.append(getattr(notifier, "_client").aclose())
        if tasks:
            await asyncio.gather(*tasks, return_exceptions=True)
        app_logger.info("[App] 应用已关闭")

    return app


app = create_app()
