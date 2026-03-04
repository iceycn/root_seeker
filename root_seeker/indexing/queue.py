"""索引任务队列（策略模式），支持 Qdrant 与 Zoekt 索引的异步执行与日志追踪。"""
from __future__ import annotations

import asyncio
import logging
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Any, Awaitable, Callable, Protocol

logger = logging.getLogger(__name__)


class IndexTaskType(str, Enum):
    QDRANT = "qdrant"
    ZOEKT = "zoekt"
    REMOVE_QDRANT = "remove_qdrant"
    REMOVE_ZOEKT = "remove_zoekt"
    RESYNC = "resync"  # 重新同步：单任务内依次执行 清除→索引→依赖图重建


class IndexTaskStatus(str, Enum):
    QUEUED = "queued"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"


@dataclass
class IndexTask:
    """单条索引任务。"""
    job_id: str
    service_name: str
    task_type: IndexTaskType
    status: IndexTaskStatus = IndexTaskStatus.QUEUED
    logs: list[str] = field(default_factory=list)
    result: Any = None  # 成功时：qdrant 为 int（块数），zoekt 为 str（message）
    error: str | None = None
    callback_url: str | None = None  # 任务完成后 POST 回调
    created_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    started_at: datetime | None = None
    finished_at: datetime | None = None

    def append_log(self, line: str) -> None:
        self.logs.append(f"[{datetime.now(timezone.utc).strftime('%H:%M:%S')}] {line}")


class IndexingQueueStrategy(Protocol):
    """索引队列策略接口，后续可扩展 Redis/数据库等队列。"""

    def submit(
        self,
        service_name: str,
        task_type: IndexTaskType,
        *,
        incremental: bool = False,
        correlation_id: str | None = None,
        callback_url: str | None = None,
        **kwargs: Any,
    ) -> str:
        """提交任务，返回 job_id。"""
        ...

    def get_task(self, job_id: str) -> IndexTask | None:
        """获取任务状态与日志。"""
        ...

    def get_task_by_service(self, service_name: str, task_type: IndexTaskType) -> IndexTask | None:
        """按 service_name 查最近一次任务（排队中或运行中）。"""
        ...

    def get_all_tasks(self) -> dict[str, IndexTask]:
        """获取所有任务（用于调试）。"""
        ...


class InMemoryIndexingQueue:
    """默认内存队列实现。"""

    def __init__(self, max_history: int = 500):
        self._queue: asyncio.Queue[IndexTask] = asyncio.Queue()
        self._tasks: dict[str, IndexTask] = {}
        self._lock = asyncio.Lock()
        self._max_history = max_history
        self._worker_task: asyncio.Task | None = None

    def submit(
        self,
        service_name: str,
        task_type: IndexTaskType,
        incremental: bool = False,
        correlation_id: str | None = None,
        callback_url: str | None = None,
        **kwargs: Any,
    ) -> str:
        job_id = uuid.uuid4().hex[:12]
        extra: dict[str, Any] = dict(kwargs)
        if task_type == IndexTaskType.QDRANT:
            extra.setdefault("incremental", incremental)
        if correlation_id is not None:
            extra["correlation_id"] = correlation_id
        task = IndexTask(
            job_id=job_id,
            service_name=service_name,
            task_type=task_type,
            result=extra,
            callback_url=callback_url,
        )
        self._tasks[job_id] = task
        self._queue.put_nowait(task)
        logger.info(f"[IndexQueue] 任务入队 job_id={job_id} service={service_name} type={task_type}")
        return job_id

    def get_task(self, job_id: str) -> IndexTask | None:
        return self._tasks.get(job_id)

    def get_task_by_service(self, service_name: str, task_type: IndexTaskType) -> IndexTask | None:
        for t in reversed(list(self._tasks.values())):
            if t.service_name == service_name and t.task_type == task_type:
                if t.status in (IndexTaskStatus.QUEUED, IndexTaskStatus.RUNNING):
                    return t
        return None

    def get_all_tasks(self) -> dict[str, IndexTask]:
        return dict(self._tasks)

    def _prune_old_tasks(self) -> None:
        """保留最近完成的任务，避免内存无限增长。"""
        completed = [
            (jid, t) for jid, t in self._tasks.items()
            if t.status in (IndexTaskStatus.COMPLETED, IndexTaskStatus.FAILED)
        ]
        if len(completed) > self._max_history:
            completed.sort(key=lambda x: x[1].finished_at or x[1].created_at)
            for jid, _ in completed[: len(completed) - self._max_history]:
                del self._tasks[jid]

    async def _worker(
        self,
        *,
        run_qdrant: Callable[[IndexTask], Awaitable[Any]],
        run_zoekt: Callable[[IndexTask], Awaitable[Any]],
        run_remove_qdrant: Callable[[IndexTask], Awaitable[Any]] | None = None,
        run_remove_zoekt: Callable[[IndexTask], Awaitable[Any]] | None = None,
        run_resync: Callable[[IndexTask], Awaitable[Any]] | None = None,
    ) -> None:
        """后台消费队列并执行。"""
        while True:
            try:
                task = await self._queue.get()
                async with self._lock:
                    if task.status != IndexTaskStatus.QUEUED:
                        continue
                    task.status = IndexTaskStatus.RUNNING
                    task.started_at = datetime.now(timezone.utc)
                    task.append_log("开始执行")

                try:
                    if task.task_type == IndexTaskType.QDRANT:
                        await run_qdrant(task)
                    elif task.task_type == IndexTaskType.ZOEKT:
                        await run_zoekt(task)
                    elif task.task_type == IndexTaskType.REMOVE_QDRANT and run_remove_qdrant:
                        await run_remove_qdrant(task)
                    elif task.task_type == IndexTaskType.REMOVE_ZOEKT and run_remove_zoekt:
                        await run_remove_zoekt(task)
                    elif task.task_type == IndexTaskType.RESYNC and run_resync:
                        await run_resync(task)
                    else:
                        task.status = IndexTaskStatus.FAILED
                        task.error = f"未知任务类型: {task.task_type}"
                except Exception as e:
                    task.status = IndexTaskStatus.FAILED
                    task.error = str(e)
                    task.append_log(f"失败: {e}")
                    logger.exception(f"[IndexQueue] 任务失败 job_id={task.job_id}")
                finally:
                    task.finished_at = datetime.now(timezone.utc)
                    self._prune_old_tasks()
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.exception(f"[IndexQueue] Worker 异常: {e}")

    def start_worker(
        self,
        *,
        run_qdrant: Callable[[IndexTask], Awaitable[Any]],
        run_zoekt: Callable[[IndexTask], Awaitable[Any]],
        run_remove_qdrant: Callable[[IndexTask], Awaitable[Any]] | None = None,
        run_remove_zoekt: Callable[[IndexTask], Awaitable[Any]] | None = None,
        run_resync: Callable[[IndexTask], Awaitable[Any]] | None = None,
    ) -> None:
        """启动后台 worker。"""
        self._worker_task = asyncio.create_task(
            self._worker(
                run_qdrant=run_qdrant,
                run_zoekt=run_zoekt,
                run_remove_qdrant=run_remove_qdrant,
                run_remove_zoekt=run_remove_zoekt,
                run_resync=run_resync,
            )
        )

    def stop_worker(self) -> None:
        if self._worker_task:
            self._worker_task.cancel()
            self._worker_task = None
