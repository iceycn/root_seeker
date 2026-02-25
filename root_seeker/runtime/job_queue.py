from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass
from datetime import datetime, timezone

from root_seeker.domain import NormalizedErrorEvent
from root_seeker.events import AnalysisCompletedEvent, AnalysisEventBus
from root_seeker.services.analyzer import AnalyzerService
from root_seeker.storage.analysis_store import AnalysisStore
from root_seeker.storage.status_store import AnalysisStatus, StatusStore

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class Job:
    analysis_id: str
    event: NormalizedErrorEvent


class JobQueue:
    def __init__(
        self,
        *,
        analyzer: AnalyzerService,
        status_store: StatusStore,
        store: AnalysisStore,
        event_bus: AnalysisEventBus,
        workers: int,
        timeout_seconds: int = 160,
    ):
        self._queue: asyncio.Queue[Job] = asyncio.Queue()
        self._analyzer = analyzer
        self._status_store = status_store
        self._store = store
        self._event_bus = event_bus
        self._workers = workers
        self._timeout_seconds = timeout_seconds
        self._tasks: list[asyncio.Task] = []

    def enqueue(self, job: Job) -> None:
        logger.info(f"[JobQueue] 任务入队，analysis_id={job.analysis_id}, service={job.event.service_name}")
        self._status_store.save(AnalysisStatus(analysis_id=job.analysis_id, status="pending"))
        self._queue.put_nowait(job)

    async def start(self) -> None:
        logger.info(f"[JobQueue] 启动任务队列，worker数={self._workers}, 超时时间={self._timeout_seconds}秒")
        for i in range(self._workers):
            self._tasks.append(asyncio.create_task(self._worker()))
        logger.info(f"[JobQueue] 任务队列启动完成")

    async def shutdown(self) -> None:
        logger.info(f"[JobQueue] 关闭任务队列，取消 {len(self._tasks)} 个 worker")
        for t in self._tasks:
            t.cancel()
        await asyncio.gather(*self._tasks, return_exceptions=True)
        logger.info("[JobQueue] 任务队列已关闭")

    async def _worker(self) -> None:
        worker_id = id(asyncio.current_task())
        logger.debug(f"[JobQueue] Worker {worker_id} 启动")
        while True:
            job = await self._queue.get()
            logger.info(f"[JobQueue] Worker {worker_id} 开始处理任务，analysis_id={job.analysis_id}")
            st = self._status_store.load(job.analysis_id) or AnalysisStatus(
                analysis_id=job.analysis_id, status="pending"
            )
            st = st.model_copy(update={"status": "running"})
            self._status_store.save(st)
            try:
                await asyncio.wait_for(
                    self._analyzer.analyze(job.event, analysis_id=job.analysis_id),
                    timeout=self._timeout_seconds,
                )
                st = st.model_copy(update={"status": "completed"})
                logger.info(f"[JobQueue] Worker {worker_id} 任务完成，analysis_id={job.analysis_id}")
            except asyncio.TimeoutError:
                st = st.model_copy(
                    update={
                        "status": "failed",
                        "error": f"Analysis timeout after {self._timeout_seconds} seconds",
                    }
                )
                logger.error(f"[JobQueue] Worker {worker_id} 任务超时，analysis_id={job.analysis_id}, 超时时间={self._timeout_seconds}秒")
            except Exception as e:
                st = st.model_copy(update={"status": "failed", "error": str(e)})
                logger.error(f"[JobQueue] Worker {worker_id} 任务失败，analysis_id={job.analysis_id}, 错误={e}", exc_info=True)
            st = st.model_copy(update={"updated_at": datetime.now(tz=timezone.utc)})
            self._status_store.save(st)

            # 触发任务完成事件，payload 与 GET /analysis/{id} 返回值一致（JSON 可序列化）
            payload: dict
            if st.status == "completed":
                report = self._store.load(job.analysis_id)
                payload = report.model_dump(mode="json") if report else st.model_dump(mode="json")
            else:
                payload = st.model_dump(mode="json")
            self._event_bus.emit(
                AnalysisCompletedEvent(analysis_id=job.analysis_id, status=st.status, payload=payload)
            )

            self._queue.task_done()
