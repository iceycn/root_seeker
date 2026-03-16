"""服务依赖图重建队列：串行执行，避免并发构建，每次仓库变更后触发。"""
from __future__ import annotations

import asyncio
import logging
from pathlib import Path
from typing import Callable

from root_seeker.config import RepoConfig
from root_seeker.services.service_graph import ServiceGraphBuilder, save_graph

logger = logging.getLogger(__name__)


class GraphRebuildQueue:
    """服务依赖图重建队列。每次仓库增加/同步后入队，串行执行避免并发构建。"""

    def __init__(
        self,
        *,
        graph_path: Path,
        get_repos: Callable[[], list[RepoConfig]],
        on_queued: Callable[[str, str | None], None] | None = None,
        on_completed: Callable[[int, str | None], None] | None = None,
    ):
        self._graph_path = graph_path
        self._get_repos = get_repos
        self._on_queued = on_queued
        self._on_completed = on_completed
        self._queue: asyncio.Queue[str | None] = asyncio.Queue(maxsize=1)  # 合并：最多一个待执行
        self._task: asyncio.Task | None = None

    def schedule_rebuild(self, correlation_id: str | None = None) -> None:
        """将服务依赖图重建加入队列。若已在队列中则跳过。入队时触发 on_queued 事件。"""
        if self._on_queued:
            from root_seeker.events import new_event_id

            event_id = new_event_id()
            try:
                self._on_queued(event_id, correlation_id)
            except Exception as e:
                logger.warning("[GraphRebuildQueue] 入队事件回调失败：%s", e)
        try:
            self._queue.put_nowait(correlation_id)
            logger.info("[GraphRebuildQueue] 已加入服务依赖图重建队列")
        except asyncio.QueueFull:
            logger.debug("[GraphRebuildQueue] 服务依赖图重建已在队列中，跳过重复加入")

    async def _worker(self) -> None:
        while True:
            try:
                correlation_id = await self._queue.get()
            except asyncio.CancelledError:
                logger.info("[GraphRebuildQueue] 服务依赖图重建 Worker 已取消")
                break

            repos = self._get_repos()
            logger.info(
                "[GraphRebuildQueue] 开始重建服务依赖图（队列触发），仓库数=%d",
                len(repos),
            )
            try:
                builder = ServiceGraphBuilder()
                graph = builder.build(repos)
                save_graph(graph, self._graph_path)
                j = graph.to_json()
                edge_count = len(j.get("edges", []))
                logger.info(
                    "[GraphRebuildQueue] 服务依赖图重建完成，边数=%d",
                    edge_count,
                )
                if self._on_completed:
                    try:
                        self._on_completed(edge_count, correlation_id)
                    except Exception as e:
                        logger.warning("[GraphRebuildQueue] 完成事件回调失败：%s", e)
            except Exception as e:
                logger.error(
                    "[GraphRebuildQueue] 服务依赖图重建失败：%s",
                    e,
                    exc_info=True,
                )

    async def start(self) -> None:
        """启动重建队列 Worker。"""
        self._task = asyncio.create_task(self._worker())
        logger.info("[GraphRebuildQueue] 服务依赖图重建队列已启动")

    async def shutdown(self) -> None:
        """关闭重建队列 Worker。"""
        if self._task:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
            self._task = None
        logger.info("[GraphRebuildQueue] 服务依赖图重建队列已关闭")
