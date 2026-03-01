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
from root_seeker.events import AnalysisEventBus, LogListener, NotifierCompletionListener
from root_seeker.runtime.job_queue import Job, JobQueue
from root_seeker.runtime.periodic_tasks import PeriodicTaskConfig, PeriodicTaskService
from root_seeker.security import build_api_key_dependency
from root_seeker.services.repo_mirror import RepoMirror, RepoSyncResult
from root_seeker.services.log_clusterer import LogClusterer
from root_seeker.ingest import parse_ingest_body, parse_log_list, to_normalized_event
from root_seeker.git_source import GitSourceService, create_storage_from_config


def create_app() -> FastAPI:
    cfg = load_config().app
    # 配置日志系统
    setup_logging(cfg.log_level)
    app_logger = logging.getLogger(__name__)
    app_logger.info(f"[App] 应用启动，日志级别={cfg.log_level}")
    
    app = FastAPI(title="RootSeeker", version="0.1.0")

    # 提前初始化 git_source 以合并仓库到 catalog（用于分析与索引）
    git_source_service: GitSourceService | None = None
    repos_for_catalog = list(cfg.repos)
    if cfg.git_source is None or cfg.git_source.enabled:
        storage_config = cfg.git_source.storage if cfg.git_source else {"type": "file", "file_path": "data/git_source.json"}
        repos_base = cfg.git_source.repos_base_dir if cfg.git_source else "data/repos_from_git"
        storage = create_storage_from_config(storage_config)
        git_source_service = GitSourceService(storage=storage, repos_base_dir=repos_base)
        git_repos = git_source_service.get_enabled_repos_as_config()
        repos_for_catalog = list(cfg.repos) + git_repos
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

    config_db = get_config_db()
    def _db_status_sync(st, service_name):
        if config_db:
            save_status_to_db(
                host=config_db.get("host", "localhost"),
                port=int(config_db.get("port", 3306)),
                user=config_db.get("user", "root"),
                password=config_db.get("password", ""),
                database=config_db.get("database", "root_seeker"),
                status=st,
                service_name=service_name,
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
    repo_mirror = RepoMirror(git_timeout_seconds=cfg.git_timeout_seconds)
    
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
        repos_for_sync = list(cfg.repos) + git_repos
        if git_repos:
            app_logger.info(f"[App] 已合并 {len(git_repos)} 个 Git 发现仓库到同步列表")

    index_semaphore = asyncio.Semaphore(cfg.auto_index_concurrency)
    indexing_qdrant: set[str] = set()  # 正在索引的 service_name，用于 GET /index/status
    indexing_zoekt: set[str] = set()   # Zoekt 索引由外部脚本执行，当前未集成
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
            repo_id = _validate_repo_id(repo_id)
            updated = git_source_service.select_branches(repo_id, branches=branches, enabled=enabled)
            if not updated:
                raise HTTPException(status_code=404, detail="repo not found")
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
        async def git_source_sync(_: None = Depends(require_api_key)) -> dict:
            """同步已配置仓库到本地，供分析使用。"""
            git_repos = git_source_service.get_enabled_repos_as_config()
            if not git_repos:
                return {"status": "ok", "message": "无已配置的仓库", "results": []}
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
            return {"status": "ok", "results": results}

        @app.post("/git-source/notify")
        async def git_source_notify(_: None = Depends(require_api_key)) -> dict:
            """仓库配置变更通知：若依等管理端在拉取/编辑/同步仓库后调用，RootSeeker 刷新 catalog。"""
            git_repos = git_source_service.get_enabled_repos_as_config()
            new_repos = list(cfg.repos) + git_repos
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
            """配置变更通知：若依等管理端保存配置后调用，RootSeeker 可据此做热重载等。"""
            app_logger.info("[App] 收到配置变更通知")
            return {"status": "ok", "message": "config change notified"}

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

    @app.get("/index/status")
    async def get_index_status(_: None = Depends(require_api_key)) -> dict[str, Any]:
        """
        返回各仓库的 Qdrant 与 Zoekt 索引状态。
        每项含：service_name, qdrant_indexed, qdrant_indexing, qdrant_count, zoekt_indexed, zoekt_indexing。
        """
        zoekt_repos: set[str] | None = None
        if zoekt is not None:
            zoekt_repos = await zoekt.list_indexed_repos()
        result: list[dict[str, Any]] = []
        for repo in repos_for_sync:
            sn = repo.service_name
            qdrant_count = 0
            if qstore is not None:
                qdrant_count = await asyncio.to_thread(
                    qstore.count_points_by_service, service_name=sn
                )
            item: dict[str, Any] = {
                "service_name": sn,
                "qdrant_indexed": qdrant_count > 0,
                "qdrant_indexing": sn in indexing_qdrant,
                "qdrant_count": qdrant_count,
                "zoekt_indexed": (sn in zoekt_repos) if zoekt_repos is not None else None,
                "zoekt_indexing": sn in indexing_zoekt,
            }
            result.append(item)
        return {"repos": result}

    @app.post("/index/repo/{service_name}")
    async def index_repo(
        service_name: str,
        incremental: bool = False,
        _: None = Depends(require_api_key),
    ) -> dict[str, int | str]:
        """
        为指定仓库建向量索引。
        incremental=true：仅索引 git pull 后的变更文件（需 ORIG_HEAD 有效），否则全量。
        """
        # 安全验证：确保 service_name 格式正确（防止注入攻击）
        if not service_name or len(service_name) > 100 or not all(c.isalnum() or c in "-_./" for c in service_name):
            raise HTTPException(status_code=400, detail="Invalid service_name format")
        app_logger.info(f"[App] 收到仓库索引请求，service={service_name}, incremental={incremental}")
        if vector_indexer is None:
            app_logger.warning("[App] 向量索引未配置")
            raise HTTPException(status_code=400, detail="vector indexing is not configured")
        candidates = router.route(service_name)
        if not candidates:
            app_logger.warning(f"[App] 未找到 service_name={service_name} 对应的仓库")
            raise HTTPException(status_code=404, detail="service_name not mapped to any repo")
        repo = candidates[0]
        try:
            indexing_qdrant.add(service_name)
            app_logger.info(f"[App] 开始索引仓库，service={service_name}, repo={repo.local_dir}")
            count = await vector_indexer.index_repo(
                repo_local_dir=repo.local_dir,
                service_name=service_name,
                incremental=incremental,
            )
            app_logger.info(f"[App] 仓库索引完成，service={service_name}, 索引块数={count}")
            return {"status": "ok", "indexed_chunks": count}
        except Exception as e:
            app_logger.error(f"[App] 仓库索引失败，service={service_name}, 错误={e}", exc_info=True)
            raise HTTPException(status_code=500, detail=f"index_repo failed: {e!s}")
        finally:
            indexing_qdrant.discard(service_name)

    @app.post("/index/repo/{service_name}/reset")
    async def reset_repo_index(
        service_name: str,
        _: None = Depends(require_api_key),
    ) -> dict[str, int | str]:
        """
        全量重置：清除该服务的向量索引，然后从头重新索引。
        用于强制重新加载、修复索引损坏等场景。
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
                return {"status": "ok", "indexed_chunks": count}
            finally:
                indexing_qdrant.discard(service_name)
        except Exception as e:
            indexing_qdrant.discard(service_name)
            app_logger.error(f"[App] 全量重置失败，service={service_name}, 错误={e}", exc_info=True)
            raise HTTPException(status_code=500, detail=f"reset failed: {e!s}")

    @app.post("/index/repo/{service_name}/clear")
    async def clear_repo_index(
        service_name: str,
        _: None = Depends(require_api_key),
    ) -> dict[str, str]:
        """仅清除该服务的向量索引，不重索引。"""
        if not service_name or len(service_name) > 100 or not all(c.isalnum() or c in "-_./" for c in service_name):
            raise HTTPException(status_code=400, detail="Invalid service_name format")
        if qstore is None:
            raise HTTPException(status_code=400, detail="vector indexing is not configured")
        try:
            await asyncio.to_thread(qstore.delete_points_by_service, service_name=service_name)
            app_logger.info(f"[App] 已清除向量，service={service_name}")
            return {"status": "ok", "message": "cleared"}
        except Exception as e:
            app_logger.error(f"[App] 清除失败，service={service_name}, 错误={e}", exc_info=True)
            raise HTTPException(status_code=500, detail=f"clear failed: {e!s}")

    @app.post("/index/reset-all")
    async def reset_all_index(
        reindex: bool = False,
        _: None = Depends(require_api_key),
    ) -> dict[str, Any]:
        """
        强制清除全部向量索引。reindex=true 时清除后按仓库排队重新索引（受 auto_index_concurrency 限制）。
        用于全量重建、修复损坏等场景。
        """
        app_logger.info(f"[App] 收到全量清除请求，reindex={reindex}")
        if vector_indexer is None or qstore is None:
            raise HTTPException(status_code=400, detail="vector indexing is not configured")
        try:
            await asyncio.to_thread(qstore.delete_collection)
            app_logger.info("[App] 已清除全部向量")
        except Exception as e:
            app_logger.error(f"[App] 清除向量失败：{e}", exc_info=True)
            raise HTTPException(status_code=500, detail=f"reset-all failed: {e!s}")
        if not reindex:
            return {"status": "ok", "cleared": True, "indexed_chunks": 0}
        errors: list[str] = []
        indexed_count = 0
        for repo in repos_for_sync:
            try:
                indexing_qdrant.add(repo.service_name)
                try:
                    async with index_semaphore:
                        count = await vector_indexer.index_repo(
                            repo_local_dir=repo.local_dir,
                            service_name=repo.service_name,
                            incremental=False,
                        )
                    indexed_count += count
                    app_logger.info(f"[App] 仓库索引完成，service={repo.service_name}, 块数={count}")
                finally:
                    indexing_qdrant.discard(repo.service_name)
            except Exception as e:
                indexing_qdrant.discard(repo.service_name)
                errors.append(f"{repo.service_name}: {e!s}")
                app_logger.error(f"[App] 索引失败：{repo.service_name}, {e}", exc_info=True)
        app_logger.info(f"[App] 全量重索引完成，indexed_chunks={indexed_count}, errors={len(errors)}")
        return {"status": "ok", "cleared": True, "indexed_chunks": indexed_count, "errors": errors}

    @app.post("/repos/full-reload")
    async def full_reload_repos(
        service_name: str | None = None,
        _: None = Depends(require_api_key),
    ) -> dict[str, Any]:
        """
        全量重新加载：先同步仓库（git pull），再清除向量并从头索引。
        service_name 可选，不传则对所有仓库执行。
        按仓库排队加载，受 auto_index_concurrency 限制。
        """
        app_logger.info(f"[App] 收到全量重载请求，service_name={service_name or 'all'}")
        if vector_indexer is None or qstore is None:
            raise HTTPException(status_code=400, detail="vector indexing is not configured")
        repos_to_process = repos_for_sync
        if service_name:
            if not all(c.isalnum() or c in "-_./" for c in service_name):
                raise HTTPException(status_code=400, detail="Invalid service_name format")
            repos_to_process = [r for r in repos_for_sync if r.service_name == service_name]
            if not repos_to_process:
                raise HTTPException(status_code=404, detail="service_name not found")
        if not repos_to_process:
            return {"status": "ok", "synced": 0, "indexed": 0, "errors": []}
        errors: list[str] = []
        synced_count = 0
        indexed_count = 0
        for repo in repos_to_process:
            try:
                sync_result = await repo_mirror.sync(repo)
                if sync_result.status in ("updated", "cloned", "no_change"):
                    synced_count += 1
                else:
                    errors.append(f"{repo.service_name}: sync {sync_result.status}")
            except Exception as e:
                errors.append(f"{repo.service_name}: sync error {e!s}")
                continue
        for repo in repos_to_process:
            try:
                await asyncio.to_thread(qstore.delete_points_by_service, service_name=repo.service_name)
                indexing_qdrant.add(repo.service_name)
                try:
                    async with index_semaphore:
                        count = await vector_indexer.index_repo(
                            repo_local_dir=repo.local_dir,
                            service_name=repo.service_name,
                            incremental=False,
                        )
                    indexed_count += count
                finally:
                    indexing_qdrant.discard(repo.service_name)
            except Exception as e:
                indexing_qdrant.discard(repo.service_name)
                errors.append(f"{repo.service_name}: index error {e!s}")
                app_logger.error(f"[App] 全量重载索引失败：{repo.service_name}, {e}", exc_info=True)
        app_logger.info(f"[App] 全量重载完成，synced={synced_count}, indexed_chunks={indexed_count}, errors={len(errors)}")
        return {"status": "ok", "synced": synced_count, "indexed": indexed_count, "errors": errors}

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

    @app.post("/repos/sync")
    async def sync_repos(
        service_name: str | None = None, _: None = Depends(require_api_key)
    ) -> dict:
        """同步仓库（含 config.repos 与 git_source 已启用仓库）。"""
        app_logger.info(f"[App] 收到仓库同步请求，service={service_name or 'all'}")
        all_repos = repos_for_sync
        if service_name:
            matches = [r for r in all_repos if r.service_name == service_name or service_name in r.repo_aliases]
        else:
            matches = list(all_repos)
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
