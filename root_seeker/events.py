"""任务完成事件与监听器。任务执行完成后触发，所有监听器可订阅。"""

from __future__ import annotations

import asyncio
import json
import logging
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, Protocol

logger = logging.getLogger(__name__)


def new_event_id() -> str:
    """生成事件唯一 ID，用于串联整条链路。"""
    return uuid.uuid4().hex


def new_correlation_id() -> str:
    """生成链路关联 ID，同一流程内的事件共享此 ID。"""
    return uuid.uuid4().hex


def _payload_to_markdown(payload: dict[str, Any]) -> str:
    """将 analysis payload（与 GET /analysis/{id} 一致）转为 Markdown。"""
    lines: list[str] = []
    lines.append(f"- analysis_id: {payload.get('analysis_id', '')}")
    if payload.get("created_at"):
        lines.append(f"- 时间: {payload['created_at']}")
    if payload.get("business_impact"):
        lines.append(f"- 业务影响: {payload['business_impact']}")
    lines.append("")
    lines.append("**摘要**")
    lines.append(payload.get("summary", ""))
    if payload.get("hypotheses"):
        lines.append("")
        lines.append("**可能原因**")
        for h in payload["hypotheses"][:8]:
            lines.append(f"- {h}")
    if payload.get("suggestions"):
        lines.append("")
        lines.append("**修改建议**")
        for s in payload["suggestions"][:10]:
            lines.append(f"- {s}")
    ev = payload.get("evidence") or {}
    files = ev.get("files") if isinstance(ev, dict) else []
    if files:
        lines.append("")
        lines.append("**关键证据**")
        for ef in files[:6]:
            loc = ef.get("file_path", "")
            if ef.get("start_line") and ef.get("end_line"):
                loc = f"{loc}:{ef['start_line']}-{ef['end_line']}"
            lines.append(f"- {loc}（{ef.get('source', '')}）")
    return "\n".join(lines)


@dataclass(frozen=True)
class AnalysisCompletedEvent:
    """分析任务完成事件。payload 与 GET /analysis/{id} 返回值结构一致。"""

    analysis_id: str
    status: str  # completed | failed
    payload: dict[str, Any]


class AnalysisCompletedListener(Protocol):
    """分析完成监听器协议。"""

    def on_analysis_completed(self, event: AnalysisCompletedEvent) -> None:
        """任务完成时调用。"""
        ...


class AnalysisEventBus:
    """分析完成事件总线，支持注册监听器并在任务完成时通知。"""

    def __init__(self) -> None:
        self._listeners: list[AnalysisCompletedListener | Callable[[AnalysisCompletedEvent], Any]] = []

    def add_listener(self, listener: AnalysisCompletedListener | Callable[[AnalysisCompletedEvent], Any]) -> None:
        """注册监听器。"""
        self._listeners.append(listener)

    def remove_listener(self, listener: AnalysisCompletedListener | Callable[[AnalysisCompletedEvent], Any]) -> None:
        """移除监听器。"""
        if listener in self._listeners:
            self._listeners.remove(listener)

    def emit(self, event: AnalysisCompletedEvent) -> None:
        """同步触发事件，通知所有监听器。"""
        for listener in self._listeners:
            try:
                if hasattr(listener, "on_analysis_completed"):
                    listener.on_analysis_completed(event)
                elif callable(listener):
                    listener(event)
            except Exception as e:
                logger.exception("[Events] 监听器执行异常: %s", e)


class LogListener:
    """默认日志监听器：将 AI 分析结果打印到日志，格式与 GET /analysis/{id} 返回值一致。"""

    def __init__(self, *, pretty: bool = True) -> None:
        self._pretty = pretty

    def on_analysis_completed(self, event: AnalysisCompletedEvent) -> None:
        payload_str = json.dumps(event.payload, ensure_ascii=False, indent=2) if self._pretty else json.dumps(
            event.payload, ensure_ascii=False
        )
        logger.info(
            "[AnalysisCompleted] analysis_id=%s status=%s\n%s",
            event.analysis_id,
            event.status,
            payload_str,
        )


@dataclass(frozen=True)
class RepoSyncCompletedEvent:
    """某个仓库同步完成事件。"""

    service_name: str
    local_dir: str
    status: str  # cloned | updated | no_change | error
    detail: str | None = None
    event_id: str = field(default_factory=new_event_id)
    correlation_id: str | None = None
    callback_url: str | None = None  # 若调用时开启回调，则索引入队后任务完成会触发回调


class RepoSyncCompletedListener(Protocol):
    """仓库同步完成监听器协议。"""

    def on_repo_sync_completed(self, event: RepoSyncCompletedEvent) -> None:
        """某个仓库同步完成时调用。"""
        ...


class RepoSyncEventBus:
    """仓库同步完成事件总线，支持注册监听器并在每个仓库同步完成时通知。"""

    def __init__(self) -> None:
        self._listeners: list[
            RepoSyncCompletedListener | Callable[[RepoSyncCompletedEvent], Any]
        ] = []

    def add_listener(
        self,
        listener: RepoSyncCompletedListener | Callable[[RepoSyncCompletedEvent], Any],
    ) -> None:
        """注册监听器。"""
        self._listeners.append(listener)

    def remove_listener(
        self,
        listener: RepoSyncCompletedListener | Callable[[RepoSyncCompletedEvent], Any],
    ) -> None:
        """移除监听器。"""
        if listener in self._listeners:
            self._listeners.remove(listener)

    def emit(self, event: RepoSyncCompletedEvent) -> None:
        """同步触发事件，通知所有监听器。"""
        for listener in self._listeners:
            try:
                if hasattr(listener, "on_repo_sync_completed"):
                    listener.on_repo_sync_completed(event)
                elif callable(listener):
                    listener(event)
            except Exception as e:
                logger.exception("[Events] 仓库同步监听器执行异常: %s", e)


class RepoSyncLogListener:
    """默认日志监听器：将仓库同步完成结果打印到日志。"""

    def on_repo_sync_completed(self, event: RepoSyncCompletedEvent) -> None:
        logger.info(
            "[RepoSyncCompleted] event_id=%s correlation_id=%s service_name=%s status=%s local_dir=%s%s",
            event.event_id,
            event.correlation_id or "-",
            event.service_name,
            event.status,
            event.local_dir,
            f" detail={event.detail}" if event.detail else "",
        )


@dataclass
class RequestSyncRepoEvent:
    """请求同步仓库事件。在接口入口注入，触发 Qdrant/Zoekt 索引入队。"""

    service_name: str
    task_types: list[str] = field(default_factory=lambda: ["qdrant"])  # qdrant | zoekt
    incremental: bool = False
    correlation_id: str | None = None
    callback_url: str | None = None  # 任务完成后 POST 回调
    skip_if_already_indexed: bool = False  # no_change 时：若 Qdrant 已有索引则跳过索引并直接回调
    event_id: str = field(default_factory=new_event_id)
    result: dict[str, Any] = field(default_factory=dict)  # 接收器可写入 job_id 等


class RequestSyncRepoListener(Protocol):
    """请求同步仓库事件监听器协议。"""

    def on_request_sync_repo(self, event: RequestSyncRepoEvent) -> None:
        """请求同步仓库时调用。"""
        ...


class RequestSyncRepoEventBus:
    """请求同步仓库事件总线。"""

    def __init__(self) -> None:
        self._listeners: list[
            RequestSyncRepoListener | Callable[[RequestSyncRepoEvent], Any]
        ] = []

    def add_listener(
        self,
        listener: RequestSyncRepoListener | Callable[[RequestSyncRepoEvent], Any],
    ) -> None:
        """注册监听器。"""
        self._listeners.append(listener)

    def remove_listener(
        self,
        listener: RequestSyncRepoListener | Callable[[RequestSyncRepoEvent], Any],
    ) -> None:
        """移除监听器。"""
        if listener in self._listeners:
            self._listeners.remove(listener)

    def emit(self, event: RequestSyncRepoEvent) -> None:
        """同步触发事件。"""
        for listener in self._listeners:
            try:
                if hasattr(listener, "on_request_sync_repo"):
                    listener.on_request_sync_repo(event)
                elif callable(listener):
                    listener(event)
            except Exception as e:
                logger.exception("[Events] 请求同步仓库监听器执行异常: %s", e)


class RequestSyncRepoLogListener:
    """默认日志监听器：将请求同步仓库事件打印到日志。"""

    def on_request_sync_repo(self, event: RequestSyncRepoEvent) -> None:
        logger.info(
            "[RequestSyncRepo] event_id=%s correlation_id=%s service_name=%s task_types=%s",
            event.event_id,
            event.correlation_id or "-",
            event.service_name,
            event.task_types,
        )


@dataclass
class RequestRemoveRepoEvent:
    """请求移除仓库事件。在接口入口注入，触发 Qdrant/Zoekt 索引清除。"""

    service_name: str
    task_types: list[str] = field(default_factory=lambda: ["qdrant", "zoekt"])
    correlation_id: str | None = None
    callback_url: str | None = None  # 任务完成后 POST 回调
    event_id: str = field(default_factory=new_event_id)
    result: dict[str, Any] = field(default_factory=dict)


class RequestRemoveRepoListener(Protocol):
    """请求移除仓库事件监听器协议。"""

    def on_request_remove_repo(self, event: RequestRemoveRepoEvent) -> None:
        """请求移除仓库时调用。"""
        ...


class RequestRemoveRepoEventBus:
    """请求移除仓库事件总线。"""

    def __init__(self) -> None:
        self._listeners: list[
            RequestRemoveRepoListener | Callable[[RequestRemoveRepoEvent], Any]
        ] = []

    def add_listener(
        self,
        listener: RequestRemoveRepoListener | Callable[[RequestRemoveRepoEvent], Any],
    ) -> None:
        self._listeners.append(listener)

    def remove_listener(
        self,
        listener: RequestRemoveRepoListener | Callable[[RequestRemoveRepoEvent], Any],
    ) -> None:
        if listener in self._listeners:
            self._listeners.remove(listener)

    def emit(self, event: RequestRemoveRepoEvent) -> None:
        for listener in self._listeners:
            try:
                if hasattr(listener, "on_request_remove_repo"):
                    listener.on_request_remove_repo(event)
                elif callable(listener):
                    listener(event)
            except Exception as e:
                logger.exception("[Events] 请求移除仓库监听器执行异常: %s", e)


class RequestRemoveRepoLogListener:
    """默认日志监听器：将请求移除仓库事件打印到日志。"""

    def on_request_remove_repo(self, event: RequestRemoveRepoEvent) -> None:
        logger.info(
            "[RequestRemoveRepo] event_id=%s correlation_id=%s service_name=%s task_types=%s",
            event.event_id,
            event.correlation_id or "-",
            event.service_name,
            event.task_types,
        )


@dataclass
class RequestResyncRepoEvent:
    """请求重新同步仓库事件。先清除后添加，添加完成后触发依赖图重建。"""

    service_name: str
    task_types: list[str] = field(default_factory=lambda: ["qdrant", "zoekt"])
    correlation_id: str | None = None
    callback_url: str | None = None  # 任务完成后 POST 回调
    event_id: str = field(default_factory=new_event_id)
    result: dict[str, Any] = field(default_factory=dict)


class RequestResyncRepoListener(Protocol):
    def on_request_resync_repo(self, event: RequestResyncRepoEvent) -> None:
        ...


class RequestResyncRepoEventBus:
    def __init__(self) -> None:
        self._listeners: list[
            RequestResyncRepoListener | Callable[[RequestResyncRepoEvent], Any]
        ] = []

    def add_listener(
        self,
        listener: RequestResyncRepoListener | Callable[[RequestResyncRepoEvent], Any],
    ) -> None:
        self._listeners.append(listener)

    def emit(self, event: RequestResyncRepoEvent) -> None:
        for listener in self._listeners:
            try:
                if hasattr(listener, "on_request_resync_repo"):
                    listener.on_request_resync_repo(event)
                elif callable(listener):
                    listener(event)
            except Exception as e:
                logger.exception("[Events] 请求重新同步监听器执行异常: %s", e)


class RequestResyncRepoLogListener:
    def on_request_resync_repo(self, event: RequestResyncRepoEvent) -> None:
        logger.info(
            "[RequestResyncRepo] event_id=%s correlation_id=%s service_name=%s",
            event.event_id,
            event.correlation_id or "-",
            event.service_name,
        )


@dataclass(frozen=True)
class ResyncCompletedEvent:
    """重新同步链路完成事件。清除→添加→依赖图重建 整条链路已结束。"""

    service_name: str
    status: str  # completed | failed
    correlation_id: str | None = None
    event_id: str = field(default_factory=new_event_id)
    indexed_chunks: int | None = None
    error: str | None = None
    callback_url: str | None = None  # 若调用时开启回调，则触发回调处理器


class ResyncCompletedListener(Protocol):
    def on_resync_completed(self, event: ResyncCompletedEvent) -> None:
        ...


class ResyncCompletedEventBus:
    def __init__(self) -> None:
        self._listeners: list[
            ResyncCompletedListener | Callable[[ResyncCompletedEvent], Any]
        ] = []

    def add_listener(
        self,
        listener: ResyncCompletedListener | Callable[[ResyncCompletedEvent], Any],
    ) -> None:
        self._listeners.append(listener)

    def emit(self, event: ResyncCompletedEvent) -> None:
        for listener in self._listeners:
            try:
                if hasattr(listener, "on_resync_completed"):
                    listener.on_resync_completed(event)
                elif callable(listener):
                    listener(event)
            except Exception as e:
                logger.exception("[Events] 重新同步完成监听器执行异常: %s", e)


class ResyncCompletedLogListener:
    def on_resync_completed(self, event: ResyncCompletedEvent) -> None:
        logger.info(
            "[ResyncCompleted] event_id=%s correlation_id=%s service_name=%s status=%s",
            event.event_id,
            event.correlation_id or "-",
            event.service_name,
            event.status,
        )


class ResyncReceiver:
    """
    重新同步接收器。与新建索引一样，将 resync 作为单个任务入队。
    执行时在一个线程中依次完成：清除→索引→依赖图重建。
    """

    def __init__(
        self,
        *,
        index_queue: object | None,
        resync_completed_event_bus: ResyncCompletedEventBus,
    ) -> None:
        self._index_queue = index_queue
        self._completed_bus = resync_completed_event_bus

    def on_request_resync_repo(self, event: RequestResyncRepoEvent) -> None:
        cid = event.correlation_id or new_correlation_id()
        if self._index_queue is None:
            self._completed_bus.emit(
                ResyncCompletedEvent(
                    service_name=event.service_name,
                    status="failed",
                    correlation_id=cid,
                    error="索引队列未启用",
                    callback_url=event.callback_url,
                )
            )
            return
        try:
            from root_seeker.indexing.queue import IndexTaskType

            job_id = self._index_queue.submit(
                service_name=event.service_name,
                task_type=IndexTaskType.RESYNC,
                correlation_id=cid,
                callback_url=event.callback_url,
            )
            event.result["resync_job_id"] = job_id
            logger.info("[ResyncReceiver] 已入队，service=%s job_id=%s", event.service_name, job_id)
        except Exception as e:
            logger.warning("[ResyncReceiver] 入队失败 service=%s: %s", event.service_name, e)
            self._completed_bus.emit(
                ResyncCompletedEvent(
                    service_name=event.service_name,
                    status="failed",
                    correlation_id=cid,
                    error=f"入队失败: {e}",
                    callback_url=event.callback_url,
                )
            )


@dataclass
class RequestResetAllEvent:
    """请求全量清除事件。reindex=true 时清除后为每个仓库入队索引。"""

    reindex: bool = False
    correlation_id: str | None = None
    callback_url: str | None = None
    event_id: str = field(default_factory=new_event_id)
    result: dict[str, Any] = field(default_factory=dict)


class RequestResetAllListener(Protocol):
    def on_request_reset_all(self, event: RequestResetAllEvent) -> None:
        ...


class RequestResetAllEventBus:
    def __init__(self) -> None:
        self._listeners: list[
            RequestResetAllListener | Callable[[RequestResetAllEvent], Any]
        ] = []

    def add_listener(
        self,
        listener: RequestResetAllListener | Callable[[RequestResetAllEvent], Any],
    ) -> None:
        self._listeners.append(listener)

    def emit(self, event: RequestResetAllEvent) -> None:
        for listener in self._listeners:
            try:
                if hasattr(listener, "on_request_reset_all"):
                    listener.on_request_reset_all(event)
                elif callable(listener):
                    listener(event)
            except Exception as e:
                logger.exception("[Events] 请求全量清除监听器执行异常: %s", e)


class RequestResetAllLogListener:
    def on_request_reset_all(self, event: RequestResetAllEvent) -> None:
        logger.info(
            "[RequestResetAll] event_id=%s correlation_id=%s reindex=%s",
            event.event_id,
            event.correlation_id or "-",
            event.reindex,
        )


@dataclass
class RequestFullReloadEvent:
    """请求全量重载事件。先同步仓库，再移除并重新索引。"""

    service_names: list[str] | None = None  # None 表示全部
    correlation_id: str | None = None
    callback_url: str | None = None
    event_id: str = field(default_factory=new_event_id)
    result: dict[str, Any] = field(default_factory=dict)


class RequestFullReloadListener(Protocol):
    def on_request_full_reload(self, event: RequestFullReloadEvent) -> None:
        ...


class RequestFullReloadEventBus:
    def __init__(self) -> None:
        self._listeners: list[
            RequestFullReloadListener | Callable[[RequestFullReloadEvent], Any]
        ] = []

    def add_listener(
        self,
        listener: RequestFullReloadListener | Callable[[RequestFullReloadEvent], Any],
    ) -> None:
        self._listeners.append(listener)

    def emit(self, event: RequestFullReloadEvent) -> None:
        for listener in self._listeners:
            try:
                if hasattr(listener, "on_request_full_reload"):
                    listener.on_request_full_reload(event)
                elif callable(listener):
                    listener(event)
            except Exception as e:
                logger.exception("[Events] 请求全量重载监听器执行异常: %s", e)


class RequestFullReloadLogListener:
    def on_request_full_reload(self, event: RequestFullReloadEvent) -> None:
        logger.info(
            "[RequestFullReload] event_id=%s correlation_id=%s service_names=%s",
            event.event_id,
            event.correlation_id or "-",
            event.service_names,
        )


@dataclass(frozen=True)
class QdrantIndexRemovedEvent:
    """某个仓库 Qdrant 索引已移除事件。"""

    service_name: str
    status: str  # completed | failed
    error: str | None = None
    event_id: str = field(default_factory=new_event_id)
    correlation_id: str | None = None
    callback_url: str | None = None  # 若调用时开启回调，则触发回调处理器


class QdrantIndexRemovedListener(Protocol):
    def on_qdrant_index_removed(self, event: QdrantIndexRemovedEvent) -> None:
        ...


class QdrantIndexRemovedEventBus:
    def __init__(self) -> None:
        self._listeners: list[
            QdrantIndexRemovedListener | Callable[[QdrantIndexRemovedEvent], Any]
        ] = []

    def add_listener(
        self,
        listener: QdrantIndexRemovedListener | Callable[[QdrantIndexRemovedEvent], Any],
    ) -> None:
        self._listeners.append(listener)

    def emit(self, event: QdrantIndexRemovedEvent) -> None:
        for listener in self._listeners:
            try:
                if hasattr(listener, "on_qdrant_index_removed"):
                    listener.on_qdrant_index_removed(event)
                elif callable(listener):
                    listener(event)
            except Exception as e:
                logger.exception("[Events] Qdrant 索引移除监听器执行异常: %s", e)


class QdrantIndexRemovedLogListener:
    def on_qdrant_index_removed(self, event: QdrantIndexRemovedEvent) -> None:
        logger.info(
            "[QdrantIndexRemoved] event_id=%s correlation_id=%s service_name=%s status=%s%s",
            event.event_id,
            event.correlation_id or "-",
            event.service_name,
            event.status,
            f" error={event.error}" if event.error else "",
        )


@dataclass(frozen=True)
class ZoektIndexRemovedEvent:
    """某个仓库 Zoekt 索引已移除事件。"""

    service_name: str
    status: str  # completed | failed
    error: str | None = None
    event_id: str = field(default_factory=new_event_id)
    correlation_id: str | None = None
    callback_url: str | None = None  # 若调用时开启回调，则触发回调处理器


class ZoektIndexRemovedListener(Protocol):
    def on_zoekt_index_removed(self, event: ZoektIndexRemovedEvent) -> None:
        ...


class ZoektIndexRemovedEventBus:
    def __init__(self) -> None:
        self._listeners: list[
            ZoektIndexRemovedListener | Callable[[ZoektIndexRemovedEvent], Any]
        ] = []

    def add_listener(
        self,
        listener: ZoektIndexRemovedListener | Callable[[ZoektIndexRemovedEvent], Any],
    ) -> None:
        self._listeners.append(listener)

    def emit(self, event: ZoektIndexRemovedEvent) -> None:
        for listener in self._listeners:
            try:
                if hasattr(listener, "on_zoekt_index_removed"):
                    listener.on_zoekt_index_removed(event)
                elif callable(listener):
                    listener(event)
            except Exception as e:
                logger.exception("[Events] Zoekt 索引移除监听器执行异常: %s", e)


class ZoektIndexRemovedLogListener:
    def on_zoekt_index_removed(self, event: ZoektIndexRemovedEvent) -> None:
        logger.info(
            "[ZoektIndexRemoved] event_id=%s correlation_id=%s service_name=%s status=%s%s",
            event.event_id,
            event.correlation_id or "-",
            event.service_name,
            event.status,
            f" error={event.error}" if event.error else "",
        )


@dataclass(frozen=True)
class QdrantIndexCompletedEvent:
    """某个仓库向量索引到 Qdrant 完成事件。"""

    service_name: str
    repo_local_dir: str
    indexed_chunks: int
    status: str  # completed | failed
    error: str | None = None
    event_id: str = field(default_factory=new_event_id)
    correlation_id: str | None = None
    callback_url: str | None = None  # 若调用时开启回调，则触发回调处理器


class QdrantIndexCompletedListener(Protocol):
    """Qdrant 索引完成监听器协议。"""

    def on_qdrant_index_completed(self, event: QdrantIndexCompletedEvent) -> None:
        """某个仓库同步到 Qdrant 完成时调用。"""
        ...


class QdrantIndexEventBus:
    """Qdrant 索引完成事件总线，支持注册监听器并在每个仓库索引完成时通知。"""

    def __init__(self) -> None:
        self._listeners: list[
            QdrantIndexCompletedListener | Callable[[QdrantIndexCompletedEvent], Any]
        ] = []

    def add_listener(
        self,
        listener: QdrantIndexCompletedListener | Callable[[QdrantIndexCompletedEvent], Any],
    ) -> None:
        """注册监听器。"""
        self._listeners.append(listener)

    def remove_listener(
        self,
        listener: QdrantIndexCompletedListener | Callable[[QdrantIndexCompletedEvent], Any],
    ) -> None:
        """移除监听器。"""
        if listener in self._listeners:
            self._listeners.remove(listener)

    def emit(self, event: QdrantIndexCompletedEvent) -> None:
        """同步触发事件，通知所有监听器。"""
        for listener in self._listeners:
            try:
                if hasattr(listener, "on_qdrant_index_completed"):
                    listener.on_qdrant_index_completed(event)
                elif callable(listener):
                    listener(event)
            except Exception as e:
                logger.exception("[Events] Qdrant 索引监听器执行异常: %s", e)


class QdrantIndexLogListener:
    """默认日志监听器：将 Qdrant 索引完成结果打印到日志。"""

    def on_qdrant_index_completed(self, event: QdrantIndexCompletedEvent) -> None:
        logger.info(
            "[QdrantIndexCompleted] event_id=%s correlation_id=%s service_name=%s status=%s indexed_chunks=%d%s",
            event.event_id,
            event.correlation_id or "-",
            event.service_name,
            event.status,
            event.indexed_chunks,
            f" error={event.error}" if event.error else "",
        )


@dataclass(frozen=True)
class ZoektIndexCompletedEvent:
    """某个仓库 Zoekt 索引完成事件。"""

    service_name: str
    repo_local_dir: str
    status: str  # completed | failed
    error: str | None = None
    event_id: str = field(default_factory=new_event_id)
    correlation_id: str | None = None
    callback_url: str | None = None  # 若调用时开启回调，则触发回调处理器


class ZoektIndexCompletedListener(Protocol):
    """Zoekt 索引完成监听器协议。"""

    def on_zoekt_index_completed(self, event: ZoektIndexCompletedEvent) -> None:
        """Zoekt 索引完成时调用。"""
        ...


class ZoektIndexCompletedEventBus:
    """Zoekt 索引完成事件总线，支持注册监听器并在每个仓库索引完成时通知。"""

    def __init__(self) -> None:
        self._listeners: list[
            ZoektIndexCompletedListener | Callable[[ZoektIndexCompletedEvent], Any]
        ] = []

    def add_listener(
        self,
        listener: ZoektIndexCompletedListener | Callable[[ZoektIndexCompletedEvent], Any],
    ) -> None:
        """注册监听器。"""
        self._listeners.append(listener)

    def remove_listener(
        self,
        listener: ZoektIndexCompletedListener | Callable[[ZoektIndexCompletedEvent], Any],
    ) -> None:
        """移除监听器。"""
        if listener in self._listeners:
            self._listeners.remove(listener)

    def emit(self, event: ZoektIndexCompletedEvent) -> None:
        """同步触发事件，通知所有监听器。"""
        for listener in self._listeners:
            try:
                if hasattr(listener, "on_zoekt_index_completed"):
                    listener.on_zoekt_index_completed(event)
                elif callable(listener):
                    listener(event)
            except Exception as e:
                logger.exception("[Events] Zoekt 索引监听器执行异常: %s", e)


class ZoektIndexLogListener:
    """默认日志监听器：将 Zoekt 索引完成结果打印到日志。"""

    def on_zoekt_index_completed(self, event: ZoektIndexCompletedEvent) -> None:
        logger.info(
            "[ZoektIndexCompleted] event_id=%s correlation_id=%s service_name=%s status=%s%s",
            event.event_id,
            event.correlation_id or "-",
            event.service_name,
            event.status,
            f" error={event.error}" if event.error else "",
        )


class IndexCallbackTrigger:
    """
    索引回调触发器：监听 Qdrant/Zoekt 完成与移除事件。
    若调用时开启了 callback_url，则触发 HTTP 回调；未开启则不触发。
    """

    def on_qdrant_index_completed(self, event: QdrantIndexCompletedEvent) -> None:
        if not event.callback_url or not event.callback_url.strip():
            return
        payload = {
            "service_name": event.service_name,
            "task_type": "qdrant",
            "status": event.status,
            "qdrant_indexed": 1 if event.status == "completed" else 0,
            "qdrant_count": event.indexed_chunks if event.status == "completed" else 0,
        }
        if event.error:
            payload["error"] = event.error
        try:
            import asyncio
            from root_seeker.indexing.callback import fire_callback
            asyncio.get_running_loop().create_task(fire_callback(event.callback_url, payload))
        except RuntimeError:
            logger.debug("[IndexCallbackTrigger] 无运行中事件循环，跳过回调")

    def on_zoekt_index_completed(self, event: ZoektIndexCompletedEvent) -> None:
        if not event.callback_url or not event.callback_url.strip():
            return
        payload = {
            "service_name": event.service_name,
            "task_type": "zoekt",
            "status": event.status,
            "zoekt_indexed": 1 if event.status == "completed" else 0,
        }
        if event.error:
            payload["error"] = event.error
        try:
            import asyncio
            from root_seeker.indexing.callback import fire_callback
            asyncio.get_running_loop().create_task(fire_callback(event.callback_url, payload))
        except RuntimeError:
            logger.debug("[IndexCallbackTrigger] 无运行中事件循环，跳过回调")

    def on_qdrant_index_removed(self, event: QdrantIndexRemovedEvent) -> None:
        if not event.callback_url or not event.callback_url.strip():
            return
        payload = {
            "service_name": event.service_name,
            "task_type": "remove_qdrant",
            "status": event.status,
            "qdrant_indexed": 0,
        }
        if event.error:
            payload["error"] = event.error
        try:
            import asyncio
            from root_seeker.indexing.callback import fire_callback
            asyncio.get_running_loop().create_task(fire_callback(event.callback_url, payload))
        except RuntimeError:
            logger.debug("[IndexCallbackTrigger] 无运行中事件循环，跳过回调")

    def on_zoekt_index_removed(self, event: ZoektIndexRemovedEvent) -> None:
        if not event.callback_url or not event.callback_url.strip():
            return
        payload = {
            "service_name": event.service_name,
            "task_type": "remove_zoekt",
            "status": event.status,
            "zoekt_indexed": 0,
        }
        if event.error:
            payload["error"] = event.error
        try:
            import asyncio
            from root_seeker.indexing.callback import fire_callback
            asyncio.get_running_loop().create_task(fire_callback(event.callback_url, payload))
        except RuntimeError:
            logger.debug("[IndexCallbackTrigger] 无运行中事件循环，跳过回调")

    def on_resync_completed(self, event: ResyncCompletedEvent) -> None:
        if not event.callback_url or not event.callback_url.strip():
            return
        payload = {
            "service_name": event.service_name,
            "task_type": "resync",
            "status": event.status,
            "qdrant_indexed": 1 if event.status == "completed" else 0,
            "qdrant_count": event.indexed_chunks or 0,
            "zoekt_indexed": 1 if event.status == "completed" else 0,
        }
        if event.error:
            payload["error"] = event.error
        try:
            import asyncio
            from root_seeker.indexing.callback import fire_callback
            asyncio.get_running_loop().create_task(fire_callback(event.callback_url, payload))
        except RuntimeError:
            logger.debug("[IndexCallbackTrigger] 无运行中事件循环，跳过回调")


@dataclass(frozen=True)
class RepoIndexSyncEvent:
    """仓库同步事件（Qdrant 索引入队时触发）。"""

    service_name: str
    job_id: str
    task_type: str  # qdrant | zoekt
    event_id: str = field(default_factory=new_event_id)
    correlation_id: str | None = None


class RepoIndexSyncListener(Protocol):
    """仓库同步事件监听器协议。"""

    def on_repo_index_sync(self, event: RepoIndexSyncEvent) -> None:
        """仓库同步时调用。"""
        ...


class RepoIndexSyncEventBus:
    """仓库同步事件总线。"""

    def __init__(self) -> None:
        self._listeners: list[
            RepoIndexSyncListener | Callable[[RepoIndexSyncEvent], Any]
        ] = []

    def add_listener(
        self,
        listener: RepoIndexSyncListener | Callable[[RepoIndexSyncEvent], Any],
    ) -> None:
        """注册监听器。"""
        self._listeners.append(listener)

    def remove_listener(
        self,
        listener: RepoIndexSyncListener | Callable[[RepoIndexSyncEvent], Any],
    ) -> None:
        """移除监听器。"""
        if listener in self._listeners:
            self._listeners.remove(listener)

    def emit(self, event: RepoIndexSyncEvent) -> None:
        """同步触发事件。"""
        for listener in self._listeners:
            try:
                if hasattr(listener, "on_repo_index_sync"):
                    listener.on_repo_index_sync(event)
                elif callable(listener):
                    listener(event)
            except Exception as e:
                logger.exception("[Events] 仓库同步监听器执行异常: %s", e)


class RepoIndexSyncLogListener:
    """默认日志监听器：将仓库同步事件打印到日志。"""

    def on_repo_index_sync(self, event: RepoIndexSyncEvent) -> None:
        logger.info(
            "[RepoIndexSync] event_id=%s correlation_id=%s service_name=%s job_id=%s task_type=%s",
            event.event_id,
            event.correlation_id or "-",
            event.service_name,
            event.job_id,
            event.task_type,
        )


class RepoSyncCompletedToRequestSyncBridge:
    """仓库同步完成 -> 请求同步仓库 桥接：收到 RepoSyncCompletedEvent 后发出 RequestSyncRepoEvent。"""

    def __init__(self, request_sync_repo_event_bus: RequestSyncRepoEventBus):
        self._bus = request_sync_repo_event_bus

    def on_repo_sync_completed(self, event: RepoSyncCompletedEvent) -> None:
        # cloned/updated/no_change 均触发索引入队，确保启用时即使无 git 变更也能索引并回调
        if event.status not in ("cloned", "updated", "no_change"):
            return
        # no_change 时：若已有索引则跳过并直接回调；否则执行索引
        skip_if_already_indexed = event.status == "no_change"
        self._bus.emit(
            RequestSyncRepoEvent(
                service_name=event.service_name,
                task_types=["qdrant", "zoekt"],
                incremental=(event.status == "updated"),
                correlation_id=event.correlation_id,
                callback_url=event.callback_url,
                skip_if_already_indexed=skip_if_already_indexed,
            )
        )


class QdrantIndexSyncReceiver:
    """
    Qdrant 仓库同步事件接收器：接收请求同步仓库事件后，将仓库入队进行 Qdrant 索引。
    """

    def __init__(
        self,
        *,
        index_queue: object,
        repo_index_sync_event_bus: RepoIndexSyncEventBus,
    ):
        self._index_queue = index_queue
        self._repo_index_sync_event_bus = repo_index_sync_event_bus

    def on_request_sync_repo(self, event: RequestSyncRepoEvent) -> None:
        if "qdrant" not in event.task_types:
            return
        try:
            from root_seeker.indexing.queue import IndexTaskType

            job_id = self._index_queue.submit(
                service_name=event.service_name,
                task_type=IndexTaskType.QDRANT,
                incremental=event.incremental,
                correlation_id=event.correlation_id,
                callback_url=event.callback_url,
                skip_if_already_indexed=event.skip_if_already_indexed,
            )
            event.result["qdrant_job_id"] = job_id
            self._repo_index_sync_event_bus.emit(
                RepoIndexSyncEvent(
                    service_name=event.service_name,
                    job_id=job_id,
                    task_type="qdrant",
                    correlation_id=event.correlation_id,
                )
            )
        except Exception as e:
            logger.warning(
                "[QdrantIndexSyncReceiver] 仓库入队失败 service=%s: %s",
                event.service_name,
                e,
            )


class ZoektIndexSyncReceiver:
    """
    Zoekt 仓库同步事件接收器：接收请求同步仓库事件后，将仓库入队进行 Zoekt 索引。
    与 Qdrant 类似流程，完成后触发依赖图重建。
    """

    def __init__(
        self,
        *,
        index_queue: object,
        repo_index_sync_event_bus: RepoIndexSyncEventBus,
    ):
        self._index_queue = index_queue
        self._repo_index_sync_event_bus = repo_index_sync_event_bus

    def on_request_sync_repo(self, event: RequestSyncRepoEvent) -> None:
        if "zoekt" not in event.task_types:
            return
        try:
            from root_seeker.indexing.queue import IndexTaskType

            job_id = self._index_queue.submit(
                service_name=event.service_name,
                task_type=IndexTaskType.ZOEKT,
                correlation_id=event.correlation_id,
                callback_url=event.callback_url,
                skip_if_already_indexed=event.skip_if_already_indexed,
            )
            event.result["zoekt_job_id"] = job_id
            self._repo_index_sync_event_bus.emit(
                RepoIndexSyncEvent(
                    service_name=event.service_name,
                    job_id=job_id,
                    task_type="zoekt",
                    correlation_id=event.correlation_id,
                )
            )
        except Exception as e:
            logger.warning(
                "[ZoektIndexSyncReceiver] 仓库入队失败 service=%s: %s",
                event.service_name,
                e,
            )


class QdrantRemoveReceiver:
    """Qdrant 移除接收器：接收请求移除仓库事件后，入队或直接清除 Qdrant 索引。"""

    def __init__(
        self,
        *,
        qstore: object,
        qdrant_index_removed_event_bus: QdrantIndexRemovedEventBus,
        index_queue: object | None = None,
    ):
        self._qstore = qstore
        self._bus = qdrant_index_removed_event_bus
        self._index_queue = index_queue

    def on_request_remove_repo(self, event: RequestRemoveRepoEvent) -> None:
        if "qdrant" not in event.task_types:
            return
        if self._index_queue is not None:
            try:
                from root_seeker.indexing.queue import IndexTaskType

                job_id = self._index_queue.submit(
                    service_name=event.service_name,
                    task_type=IndexTaskType.REMOVE_QDRANT,
                    correlation_id=event.correlation_id,
                    callback_url=event.callback_url,
                )
                event.result["qdrant_remove_job_id"] = job_id
            except Exception as e:
                logger.warning(
                    "[QdrantRemoveReceiver] 入队失败 service=%s: %s",
                    event.service_name,
                    e,
                )
            return

        def _do_delete() -> None:
            try:
                self._qstore.delete_points_by_service(service_name=event.service_name)
                self._bus.emit(
                    QdrantIndexRemovedEvent(
                        service_name=event.service_name,
                        status="completed",
                        correlation_id=event.correlation_id,
                        callback_url=event.callback_url,
                    )
                )
            except Exception as e:
                logger.warning(
                    "[QdrantRemoveReceiver] Qdrant 移除失败 service=%s: %s",
                    event.service_name,
                    e,
                )
                self._bus.emit(
                    QdrantIndexRemovedEvent(
                        service_name=event.service_name,
                        status="failed",
                        error=str(e),
                        correlation_id=event.correlation_id,
                        callback_url=event.callback_url,
                    )
                )

        try:
            loop = asyncio.get_running_loop()
            loop.run_in_executor(None, _do_delete)
        except RuntimeError:
            _do_delete()


class ZoektRemoveReceiver:
    """Zoekt 移除接收器：接收请求移除仓库事件后，入队或直接清除 Zoekt 索引。"""

    def __init__(
        self,
        *,
        zoekt_index_dir: Path,
        zoekt_index_removed_event_bus: ZoektIndexRemovedEventBus,
        index_queue: object | None = None,
    ):
        self._index_dir = zoekt_index_dir
        self._bus = zoekt_index_removed_event_bus
        self._index_queue = index_queue

    def on_request_remove_repo(self, event: RequestRemoveRepoEvent) -> None:
        if "zoekt" not in event.task_types:
            return
        if self._index_queue is not None:
            try:
                from root_seeker.indexing.queue import IndexTaskType

                job_id = self._index_queue.submit(
                    service_name=event.service_name,
                    task_type=IndexTaskType.REMOVE_ZOEKT,
                    correlation_id=event.correlation_id,
                    callback_url=event.callback_url,
                )
                event.result["zoekt_remove_job_id"] = job_id
            except Exception as e:
                logger.warning(
                    "[ZoektRemoveReceiver] 入队失败 service=%s: %s",
                    event.service_name,
                    e,
                )
            return

        def _do_remove() -> None:
            import glob
            try:
                if not self._index_dir.exists():
                    self._bus.emit(
                        ZoektIndexRemovedEvent(
                            service_name=event.service_name,
                            status="completed",
                            correlation_id=event.correlation_id,
                            callback_url=event.callback_url,
                        )
                    )
                    return
                for f in glob.glob(str(self._index_dir / "*")):
                    p = Path(f)
                    if p.is_file() and event.service_name in p.name:
                        p.unlink(missing_ok=True)
                self._bus.emit(
                    ZoektIndexRemovedEvent(
                        service_name=event.service_name,
                        status="completed",
                        correlation_id=event.correlation_id,
                        callback_url=event.callback_url,
                    )
                )
            except Exception as e:
                logger.warning(
                    "[ZoektRemoveReceiver] Zoekt 移除失败 service=%s: %s",
                    event.service_name,
                    e,
                )
                self._bus.emit(
                    ZoektIndexRemovedEvent(
                        service_name=event.service_name,
                        status="failed",
                        error=str(e),
                        correlation_id=event.correlation_id,
                        callback_url=event.callback_url,
                    )
                )

        try:
            loop = asyncio.get_running_loop()
            loop.run_in_executor(None, _do_remove)
        except RuntimeError:
            _do_remove()


@dataclass(frozen=True)
class GraphRebuildQueuedEvent:
    """服务依赖图重建入队事件。"""

    event_id: str = field(default_factory=new_event_id)
    correlation_id: str | None = None


class GraphRebuildQueuedListener(Protocol):
    """服务依赖图重建入队监听器协议。"""

    def on_graph_rebuild_queued(self, event: GraphRebuildQueuedEvent) -> None:
        """依赖图重建入队时调用。"""
        ...


class GraphRebuildEventBus:
    """服务依赖图重建事件总线，入队时通知。"""

    def __init__(self) -> None:
        self._listeners: list[
            GraphRebuildQueuedListener | Callable[[GraphRebuildQueuedEvent], Any]
        ] = []

    def add_listener(
        self,
        listener: GraphRebuildQueuedListener | Callable[[GraphRebuildQueuedEvent], Any],
    ) -> None:
        """注册监听器。"""
        self._listeners.append(listener)

    def remove_listener(
        self,
        listener: GraphRebuildQueuedListener | Callable[[GraphRebuildQueuedEvent], Any],
    ) -> None:
        """移除监听器。"""
        if listener in self._listeners:
            self._listeners.remove(listener)

    def emit(self, event: GraphRebuildQueuedEvent) -> None:
        """同步触发事件，通知所有监听器。"""
        for listener in self._listeners:
            try:
                if hasattr(listener, "on_graph_rebuild_queued"):
                    listener.on_graph_rebuild_queued(event)
                elif callable(listener):
                    listener(event)
            except Exception as e:
                logger.exception("[Events] 依赖图重建监听器执行异常: %s", e)


class GraphRebuildLogListener:
    """默认日志监听器：将依赖图重建入队结果打印到日志。"""

    def on_graph_rebuild_queued(self, event: GraphRebuildQueuedEvent) -> None:
        logger.info(
            "[GraphRebuildQueued] event_id=%s correlation_id=%s",
            event.event_id,
            event.correlation_id or "-",
        )


@dataclass(frozen=True)
class GraphRebuildCompletedEvent:
    """服务依赖图重建完成事件。"""

    edge_count: int
    event_id: str = field(default_factory=new_event_id)
    correlation_id: str | None = None


class GraphRebuildCompletedListener(Protocol):
    """服务依赖图重建完成监听器协议。"""

    def on_graph_rebuild_completed(self, event: GraphRebuildCompletedEvent) -> None:
        """依赖图重建完成时调用。"""
        ...


class GraphRebuildCompletedEventBus:
    """服务依赖图重建完成事件总线。"""

    def __init__(self) -> None:
        self._listeners: list[
            GraphRebuildCompletedListener | Callable[[GraphRebuildCompletedEvent], Any]
        ] = []

    def add_listener(
        self,
        listener: GraphRebuildCompletedListener | Callable[[GraphRebuildCompletedEvent], Any],
    ) -> None:
        """注册监听器。"""
        self._listeners.append(listener)

    def remove_listener(
        self,
        listener: GraphRebuildCompletedListener | Callable[[GraphRebuildCompletedEvent], Any],
    ) -> None:
        """移除监听器。"""
        if listener in self._listeners:
            self._listeners.remove(listener)

    def emit(self, event: GraphRebuildCompletedEvent) -> None:
        """同步触发事件。"""
        for listener in self._listeners:
            try:
                if hasattr(listener, "on_graph_rebuild_completed"):
                    listener.on_graph_rebuild_completed(event)
                elif callable(listener):
                    listener(event)
            except Exception as e:
                logger.exception("[Events] 依赖图重建完成监听器执行异常: %s", e)


class GraphRebuildCompletedLogListener:
    """默认日志监听器：将依赖图重建完成结果打印到日志。"""

    def on_graph_rebuild_completed(self, event: GraphRebuildCompletedEvent) -> None:
        logger.info(
            "[GraphRebuildCompleted] event_id=%s correlation_id=%s edge_count=%d",
            event.event_id,
            event.correlation_id or "-",
            event.edge_count,
        )


class NotifierCompletionListener:
    """
    监听完成事件，将分析报告推送到配置的 Notifier（企业微信、钉钉等）。
    仅当 status=completed 且 payload 含 summary 时发送。
    """

    def __init__(self, notifiers: list) -> None:
        self._notifiers = notifiers or []

    def on_analysis_completed(self, event: AnalysisCompletedEvent) -> None:
        if event.status != "completed" or "summary" not in event.payload:
            return
        if not self._notifiers:
            return
        markdown = _payload_to_markdown(event.payload)
        service_name = event.payload.get("service_name", "unknown")
        title = f"错误分析：{service_name}"

        async def _send() -> None:
            for n in self._notifiers:
                try:
                    if hasattr(n, "send_markdown"):
                        await n.send_markdown(title=title, markdown=markdown)
                except Exception as e:
                    logger.warning("[NotifierCompletionListener] 推送失败: %s", e)

        try:
            loop = asyncio.get_running_loop()
            loop.create_task(_send())
        except RuntimeError:
            asyncio.run(_send())
