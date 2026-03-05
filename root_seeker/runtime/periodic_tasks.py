"""
定时任务服务：定期同步仓库并更新向量索引。

功能：
1. 定期执行 git pull 同步仓库
2. 同步完成后自动触发向量索引更新（如果启用）
3. 支持配置同步间隔、索引间隔、并发数等
"""
from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Callable

from root_seeker.config import AppConfig, RepoConfig
from root_seeker.services.repo_mirror import RepoMirror, RepoSyncResult
from root_seeker.services.vector_indexer import VectorIndexer

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class PeriodicTaskConfig:
    """定时任务配置"""
    periodic_tasks_enabled: bool = False
    auto_sync_enabled: bool = False
    auto_sync_interval_seconds: int = 3600
    auto_index_enabled: bool = False
    auto_index_after_sync: bool = True
    auto_index_interval_seconds: int = 7200
    auto_sync_concurrency: int = 8
    auto_index_concurrency: int = 1


class PeriodicTaskService:
    """定时任务服务：定期同步仓库并更新向量索引"""

    def __init__(
        self,
        *,
        cfg: PeriodicTaskConfig,
        repos: list[RepoConfig],
        repo_mirror: RepoMirror,
        vector_indexer: VectorIndexer | None = None,
        index_semaphore: asyncio.Semaphore | None = None,
        index_queue: object | None = None,
        on_repos_updated: Callable[[str | None], None] | None = None,
        on_repo_sync_completed: Callable[[RepoSyncResult, str | None], None] | None = None,
        on_qdrant_index_completed: Callable[[str, str, int, str | None], None] | None = None,
    ):
        self._cfg = cfg
        self._repos = repos
        self._repo_mirror = repo_mirror
        self._vector_indexer = vector_indexer
        self._index_semaphore = index_semaphore or asyncio.Semaphore(1)
        self._index_queue = index_queue
        self._on_repos_updated = on_repos_updated
        self._on_repo_sync_completed = on_repo_sync_completed
        self._on_qdrant_index_completed = on_qdrant_index_completed
        self._sync_task: asyncio.Task | None = None
        self._index_task: asyncio.Task | None = None
        self._running = False
    
    async def start(self) -> None:
        """启动定时任务"""
        # 检查总开关
        if not self._cfg.periodic_tasks_enabled:
            logger.info("[PeriodicTaskService] 定时任务功能未启用（periodic_tasks_enabled=false），跳过启动")
            return
        
        if not self._cfg.auto_sync_enabled and not self._cfg.auto_index_enabled:
            logger.info("[PeriodicTaskService] 定时任务未启用（auto_sync_enabled 和 auto_index_enabled 均为 false），跳过启动")
            return
        
        self._running = True
        
        # 启动仓库同步定时任务
        if self._cfg.auto_sync_enabled:
            self._sync_task = asyncio.create_task(self._sync_loop())
            logger.info(
                f"[PeriodicTaskService] 仓库同步定时任务已启动，间隔={self._cfg.auto_sync_interval_seconds}秒"
            )
        
        # 启动向量索引定时任务（仅在 auto_index_after_sync=false 时独立运行）
        if self._cfg.auto_index_enabled and not self._cfg.auto_index_after_sync:
            self._index_task = asyncio.create_task(self._index_loop())
            logger.info(
                f"[PeriodicTaskService] 向量索引定时任务已启动，间隔={self._cfg.auto_index_interval_seconds}秒"
            )
    
    async def stop(self) -> None:
        """停止定时任务"""
        self._running = False
        
        if self._sync_task:
            self._sync_task.cancel()
            try:
                await self._sync_task
            except asyncio.CancelledError:
                pass
            logger.info("[PeriodicTaskService] 仓库同步定时任务已停止")
        
        if self._index_task:
            self._index_task.cancel()
            try:
                await self._index_task
            except asyncio.CancelledError:
                pass
            logger.info("[PeriodicTaskService] 向量索引定时任务已停止")
    
    async def _sync_loop(self) -> None:
        """仓库同步循环"""
        while self._running:
            try:
                logger.info(f"[PeriodicTaskService] 开始定时仓库同步，仓库数={len(self._repos)}")
                await self._sync_all_repos()
                logger.info("[PeriodicTaskService] 定时仓库同步完成")
            except Exception as e:
                logger.error(f"[PeriodicTaskService] 定时仓库同步失败：{e}", exc_info=True)
            
            # 等待指定间隔
            try:
                await asyncio.sleep(self._cfg.auto_sync_interval_seconds)
            except asyncio.CancelledError:
                break
    
    async def _index_loop(self) -> None:
        """向量索引更新循环（独立运行，不依赖同步）"""
        while self._running:
            try:
                logger.info(f"[PeriodicTaskService] 开始定时向量索引更新，仓库数={len(self._repos)}")
                await self._index_all_repos()
                logger.info("[PeriodicTaskService] 定时向量索引更新完成")
            except Exception as e:
                logger.error(f"[PeriodicTaskService] 定时向量索引更新失败：{e}", exc_info=True)
            
            # 等待指定间隔
            try:
                await asyncio.sleep(self._cfg.auto_index_interval_seconds)
            except asyncio.CancelledError:
                break
    
    async def _sync_all_repos(self) -> None:
        """同步所有仓库"""
        if not self._repos:
            logger.debug("[PeriodicTaskService] 没有配置仓库，跳过同步")
            return

        correlation_id = None
        try:
            from root_seeker.events import new_correlation_id
            correlation_id = new_correlation_id()
        except Exception:
            pass

        sem = asyncio.Semaphore(self._cfg.auto_sync_concurrency)
        
        async def _sync_one(repo: RepoConfig) -> tuple[str, RepoSyncResult]:
            async with sem:
                logger.debug(f"[PeriodicTaskService] 同步仓库：{repo.service_name}")
                return (repo.service_name, await self._repo_mirror.sync(repo))
        
        results = await asyncio.gather(*[_sync_one(r) for r in self._repos], return_exceptions=True)
        
        success_count = 0
        error_count = 0
        no_change_count = 0
        updated_repos: list[str] = []
        updated_status: dict[str, str] = {}  # service_name -> "updated" | "cloned"
        
        for result in results:
            if isinstance(result, Exception):
                error_count += 1
                logger.error(f"[PeriodicTaskService] 仓库同步异常：{result}", exc_info=True)
                continue

            service_name, sync_result = result
            if self._on_repo_sync_completed:
                try:
                    self._on_repo_sync_completed(sync_result, correlation_id)
                except Exception as e:
                    logger.warning("[PeriodicTaskService] 仓库同步完成回调失败：%s", e)

            if sync_result.status == "updated":
                success_count += 1
                updated_repos.append(service_name)
                updated_status[service_name] = "updated"
                logger.info(f"[PeriodicTaskService] 仓库有更新：{service_name}")
            elif sync_result.status == "cloned":
                success_count += 1
                updated_repos.append(service_name)  # 新克隆的仓库也需要索引
                updated_status[service_name] = "cloned"
                logger.info(f"[PeriodicTaskService] 仓库已克隆：{service_name}")
            elif sync_result.status == "no_change":
                success_count += 1
                no_change_count += 1
                logger.debug(f"[PeriodicTaskService] 仓库无变更：{service_name}")
            else:
                error_count += 1
                logger.warning(
                    f"[PeriodicTaskService] 仓库同步失败：{service_name}, "
                    f"status={sync_result.status}, detail={sync_result.detail}"
                )
        
        logger.info(
            f"[PeriodicTaskService] 仓库同步完成，成功={success_count}, 失败={error_count}, "
            f"有更新={len(updated_repos)}, 无变更={no_change_count}"
        )

        # 如果启用自动索引且同步后有更新，只为有变更的仓库触发向量索引更新
        # 当使用 index_queue 时，由 QdrantIndexSyncReceiver 接收 RepoSyncCompletedEvent 后入队，此处跳过
        if (
            self._cfg.auto_index_enabled
            and self._cfg.auto_index_after_sync
            and updated_repos
            and self._vector_indexer is not None
            and self._index_queue is None
        ):
            # updated_status: updated=git pull 有变更（可增量）; cloned=新克隆（需全量）
            logger.info(
                f"[PeriodicTaskService] 检测到 {len(updated_repos)} 个仓库有变更，开始自动触发向量索引更新"
            )
            asyncio.create_task(
                self._index_repos(updated_repos, updated_status, correlation_id)
            )
        elif updated_repos and self._index_queue is not None:
            logger.info(
                f"[PeriodicTaskService] 检测到 {len(updated_repos)} 个仓库有变更，"
                "由 QdrantIndexSyncReceiver 接收仓库同步事件后入队"
            )
        elif updated_repos:
            logger.debug(
                f"[PeriodicTaskService] 检测到 {len(updated_repos)} 个仓库有变更，"
                f"但自动索引未启用（auto_index_enabled={self._cfg.auto_index_enabled}, "
                f"auto_index_after_sync={self._cfg.auto_index_after_sync}）"
            )

        # 仓库有变更时触发服务依赖图重建（入队串行执行）
        if updated_repos and self._on_repos_updated:
            try:
                self._on_repos_updated(correlation_id)
            except Exception as e:
                logger.warning("[PeriodicTaskService] 触发服务依赖图重建失败：%s", e)
    
    async def _index_all_repos(self) -> None:
        """为所有仓库更新向量索引"""
        if not self._repos:
            logger.debug("[PeriodicTaskService] 没有配置仓库，跳过索引更新")
            return
        
        if self._vector_indexer is None:
            logger.warning("[PeriodicTaskService] 向量索引器未配置，跳过索引更新")
            return
        
        repo_names = [r.service_name for r in self._repos]
        await self._index_repos(
            repo_names, updated_status=None, correlation_id=None
        )  # 全量，非 sync 触发
    
    async def _index_repos(
        self,
        service_names: list[str],
        updated_status: dict[str, str] | None = None,
        correlation_id: str | None = None,
    ) -> None:
        """为指定的服务更新向量索引。updated_status 为 sync 结果，用于决定是否增量索引。"""
        if self._vector_indexer is None:
            logger.warning("[PeriodicTaskService] 向量索引器未配置，跳过索引更新")
            return

        if not service_names:
            logger.debug("[PeriodicTaskService] 没有需要索引的服务，跳过")
            return

        status_map = updated_status or {}
        logger.info(f"[PeriodicTaskService] 开始为 {len(service_names)} 个服务更新向量索引")
        
        # 找到对应的仓库配置
        repo_map = {r.service_name: r for r in self._repos}
        
        success_count = 0
        error_count = 0
        
        for service_name in service_names:
            repo = repo_map.get(service_name)
            if not repo:
                logger.warning(f"[PeriodicTaskService] 未找到服务 {service_name} 的仓库配置，跳过索引")
                error_count += 1
                continue
            
            # updated=pull 有变更，可尝试增量；cloned=新克隆，必须全量
            incremental = status_map.get(service_name) == "updated"
            try:
                async with self._index_semaphore:
                    logger.info(
                        f"[PeriodicTaskService] 开始索引仓库：{service_name}, "
                        f"repo={repo.local_dir}, incremental={incremental}"
                    )
                    count = await self._vector_indexer.index_repo(
                        repo_local_dir=repo.local_dir,
                        service_name=service_name,
                        incremental=incremental,
                    )
                logger.info(f"[PeriodicTaskService] 仓库索引完成：{service_name}, 索引块数={count}")
                success_count += 1
                if self._on_qdrant_index_completed:
                    try:
                        self._on_qdrant_index_completed(
                            service_name, repo.local_dir, count, correlation_id
                        )
                    except Exception as cb_e:
                        logger.warning("[PeriodicTaskService] Qdrant 索引完成回调失败：%s", cb_e)
            except Exception as e:
                error_count += 1
                logger.error(
                    f"[PeriodicTaskService] 仓库索引失败：{service_name}, 错误={e}",
                    exc_info=True,
                )
        
        logger.info(
            f"[PeriodicTaskService] 向量索引更新完成，成功={success_count}, 失败={error_count}"
        )
