from __future__ import annotations

import asyncio
import logging
import subprocess
import uuid
from dataclasses import dataclass
from pathlib import Path

from qdrant_client.http.models import PointStruct

from root_seeker.indexing.chunker import CodeChunk, TreeSitterChunker
from root_seeker.providers.embedding import EmbeddingProvider
from root_seeker.providers.qdrant import QdrantVectorStore

logger = logging.getLogger(__name__)

# 支持增量索引的代码文件后缀
_INDEXABLE_SUFFIXES = {".py", ".java"}


@dataclass(frozen=True)
class VectorIndexConfig:
    batch_size: int = 64


def _get_changed_files(repo_local_dir: str) -> list[str] | None:
    """
    获取 git pull 后的变更文件列表（依赖 ORIG_HEAD，pull 后有效）。
    返回 None 表示无法增量（如新 clone、ORIG_HEAD 不存在），应回退全量。
    """
    try:
        r = subprocess.run(
            ["git", "-C", repo_local_dir, "diff", "--name-only", "ORIG_HEAD", "HEAD"],
            capture_output=True,
            text=True,
            timeout=30,
        )
        if r.returncode != 0:
            return None
        files = [f.strip() for f in (r.stdout or "").strip().split("\n") if f.strip()]
        return [f for f in files if Path(f).suffix in _INDEXABLE_SUFFIXES]
    except Exception:
        return None


class VectorIndexer:
    def __init__(
        self,
        *,
        cfg: VectorIndexConfig,
        chunker: TreeSitterChunker,
        embedder: EmbeddingProvider,
        store: QdrantVectorStore,
    ):
        self._cfg = cfg
        self._chunker = chunker
        self._embedder = embedder
        self._store = store

    async def index_repo(
        self,
        *,
        repo_local_dir: str,
        service_name: str,
        incremental: bool = False,
    ) -> int:
        """
        索引仓库。incremental=True 时尝试仅索引变更文件（需 pull 后 ORIG_HEAD 有效），
        失败则回退全量。
        """
        if incremental:
            changed = await asyncio.to_thread(_get_changed_files, repo_local_dir)
            if changed is not None and len(changed) > 0:
                return await self._index_changed_files(
                    repo_local_dir=repo_local_dir,
                    service_name=service_name,
                    file_paths=changed,
                )
            if changed is not None and len(changed) == 0:
                logger.debug(f"[VectorIndexer] 仓库无代码变更，跳过索引：{service_name}")
                return 0
            logger.debug(f"[VectorIndexer] 增量检测失败，回退全量索引：{service_name}")

        return await self._index_full(repo_local_dir=repo_local_dir, service_name=service_name)

    async def _index_full(self, *, repo_local_dir: str, service_name: str) -> int:
        """全量索引仓库。"""
        chunks = self._chunker.chunk_repo(repo_local_dir=repo_local_dir)
        if not chunks:
            return 0

        await asyncio.to_thread(self._store.ensure_collection, vector_size=self._embedder.dimension)

        total = 0
        for batch in _batched(chunks, self._cfg.batch_size):
            vectors = await self._embedder.embed_texts([c.text for c in batch])
            points = [
                PointStruct(
                    id=_chunk_id(c),
                    vector=v,
                    payload={
                        "service_name": service_name,
                        "repo_local_dir": c.repo_local_dir,
                        "file_path": c.file_path,
                        "language": c.language,
                        "symbol": c.symbol or "",
                        "start_line": c.start_line,
                        "end_line": c.end_line,
                        "text": c.text,
                    },
                )
                for c, v in zip(batch, vectors, strict=True)
            ]
            await asyncio.to_thread(self._store.upsert_points, points)
            total += len(points)
        return total

    async def _index_changed_files(
        self,
        *,
        repo_local_dir: str,
        service_name: str,
        file_paths: list[str],
    ) -> int:
        """仅索引变更文件：先删旧点，再 chunk 并 upsert。"""
        await asyncio.to_thread(self._store.ensure_collection, vector_size=self._embedder.dimension)

        total = 0
        for file_path in file_paths:
            await asyncio.to_thread(
                self._store.delete_points_by_file,
                service_name=service_name,
                file_path=file_path,
                repo_local_dir=repo_local_dir,
            )
            chunks = self._chunker.chunk_file(
                repo_local_dir=repo_local_dir,
                file_path=file_path,
            )
            if not chunks:
                continue
            for batch in _batched(chunks, self._cfg.batch_size):
                vectors = await self._embedder.embed_texts([c.text for c in batch])
                points = [
                    PointStruct(
                        id=_chunk_id(c),
                        vector=v,
                        payload={
                            "service_name": service_name,
                            "repo_local_dir": c.repo_local_dir,
                            "file_path": c.file_path,
                            "language": c.language,
                            "symbol": c.symbol or "",
                            "start_line": c.start_line,
                            "end_line": c.end_line,
                            "text": c.text,
                        },
                    )
                    for c, v in zip(batch, vectors, strict=True)
                ]
                await asyncio.to_thread(self._store.upsert_points, points)
                total += len(points)
        return total


def _chunk_id(c: CodeChunk) -> str:
    s = f"{c.repo_local_dir}:{c.file_path}:{c.start_line}:{c.end_line}:{c.symbol or ''}"
    return str(uuid.uuid5(uuid.NAMESPACE_DNS, s))


def _batched(items: list[CodeChunk], batch_size: int):
    for i in range(0, len(items), batch_size):
        yield items[i : i + batch_size]
