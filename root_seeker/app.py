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

from root_seeker.config import load_config
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
from root_seeker.events import AnalysisEventBus, LogListener, NotifierCompletionListener
from root_seeker.runtime.job_queue import Job, JobQueue
from root_seeker.runtime.periodic_tasks import PeriodicTaskConfig, PeriodicTaskService
from root_seeker.security import build_api_key_dependency
from root_seeker.services.repo_mirror import RepoMirror
from root_seeker.ingest import parse_ingest_body, to_normalized_event


def create_app() -> FastAPI:
    cfg = load_config().app
    # 配置日志系统
    setup_logging(cfg.log_level)
    app_logger = logging.getLogger(__name__)
    app_logger.info(f"[App] 应用启动，日志级别={cfg.log_level}")
    
    app = FastAPI(title="RootSeeker", version="0.1.0")

    catalog = RepoCatalog(repos=cfg.repos)
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
    if cfg.llm is not None:
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
            QdrantConfig(url=cfg.qdrant.url, api_key=cfg.qdrant.api_key, collection=cfg.qdrant.collection)
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

    job_queue = JobQueue(
        analyzer=analyzer,
        status_store=status_store,
        store=store,
        event_bus=event_bus,
        workers=cfg.analysis_workers,
        timeout_seconds=cfg.analysis_timeout_seconds,
    )
    repo_mirror = RepoMirror(git_timeout_seconds=cfg.git_timeout_seconds)
    
    # 创建定时任务服务
    periodic_task_service = PeriodicTaskService(
        cfg=PeriodicTaskConfig(
            periodic_tasks_enabled=cfg.periodic_tasks_enabled,
            auto_sync_enabled=cfg.auto_sync_enabled,
            auto_sync_interval_seconds=cfg.auto_sync_interval_seconds,
            auto_index_enabled=cfg.auto_index_enabled,
            auto_index_after_sync=cfg.auto_index_after_sync,
            auto_index_interval_seconds=cfg.auto_index_interval_seconds,
            auto_sync_concurrency=cfg.auto_sync_concurrency,
        ),
        repos=cfg.repos,
        repo_mirror=repo_mirror,
        vector_indexer=vector_indexer,
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
        return status.model_dump()

    @app.post("/index/repo/{service_name}")
    async def index_repo(service_name: str, _: None = Depends(require_api_key)) -> dict[str, int | str]:
        # 安全验证：确保 service_name 格式正确（防止注入攻击）
        if not service_name or len(service_name) > 100 or not all(c.isalnum() or c in "-_./" for c in service_name):
            raise HTTPException(status_code=400, detail="Invalid service_name format")
        app_logger.info(f"[App] 收到仓库索引请求，service={service_name}")
        if vector_indexer is None:
            app_logger.warning("[App] 向量索引未配置")
            raise HTTPException(status_code=400, detail="vector indexing is not configured")
        candidates = router.route(service_name)
        if not candidates:
            app_logger.warning(f"[App] 未找到 service_name={service_name} 对应的仓库")
            raise HTTPException(status_code=404, detail="service_name not mapped to any repo")
        repo = candidates[0]
        try:
            app_logger.info(f"[App] 开始索引仓库，service={service_name}, repo={repo.local_dir}")
            count = await vector_indexer.index_repo(repo_local_dir=repo.local_dir, service_name=service_name)
            app_logger.info(f"[App] 仓库索引完成，service={service_name}, 索引块数={count}")
            return {"status": "ok", "indexed_chunks": count}
        except Exception as e:
            app_logger.error(f"[App] 仓库索引失败，service={service_name}, 错误={e}", exc_info=True)
            raise HTTPException(status_code=500, detail=f"index_repo failed: {e!s}")

    @app.get("/graph")
    async def get_graph() -> dict:
        """返回完整服务依赖图（caller -> callee 边列表），便于查看各项目依赖关系。"""
        graph = load_graph(graph_path)
        if graph is None:
            raise HTTPException(status_code=404, detail="service graph not built, call POST /graph/rebuild first")
        edges = graph.to_json()
        summary = [{"caller": e["caller"], "callee": e["callee"]} for e in edges]
        return {"edges": edges, "summary": summary, "total_edges": len(edges)}

    @app.post("/graph/rebuild")
    async def rebuild_graph(_: None = Depends(require_api_key)) -> dict[str, int | str]:
        app_logger.info("[App] 开始重建服务依赖图")
        try:
            builder = ServiceGraphBuilder()
            graph = builder.build(cfg.repos)
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

    @app.post("/repos/sync")
    async def sync_repos(
        service_name: str | None = None, _: None = Depends(require_api_key)
    ) -> dict:
        app_logger.info(f"[App] 收到仓库同步请求，service={service_name or 'all'}")
        if service_name:
            matches = [r for r in cfg.repos if r.service_name == service_name or service_name in r.repo_aliases]
        else:
            matches = list(cfg.repos)
        if not matches:
            app_logger.warning(f"[App] 未找到匹配的仓库，service={service_name}")
            raise HTTPException(status_code=404, detail="no repos matched")

        app_logger.info(f"[App] 开始同步 {len(matches)} 个仓库")
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
            app_logger.info(f"[App] 仓库同步完成，成功={success_count}, 失败={error_count}")
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

    @app.on_event("startup")
    async def _startup() -> None:
        app_logger.info("[App] 应用启动中...")
        await job_queue.start()
        await periodic_task_service.start()
        app_logger.info("[App] 应用启动完成")

    @app.on_event("shutdown")
    async def _shutdown() -> None:
        app_logger.info("[App] 应用关闭中...")
        await periodic_task_service.stop()
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
