from __future__ import annotations

import asyncio
import uuid
from dataclasses import dataclass

from qdrant_client.http.models import PointStruct

from root_seeker.indexing.chunker import CodeChunk, TreeSitterChunker
from root_seeker.providers.embedding import EmbeddingProvider
from root_seeker.providers.qdrant import QdrantVectorStore


@dataclass(frozen=True)
class VectorIndexConfig:
    batch_size: int = 64


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

    async def index_repo(self, *, repo_local_dir: str, service_name: str) -> int:
        chunks = self._chunker.chunk_repo(repo_local_dir=repo_local_dir)
        if not chunks:
            return 0

        await asyncio.to_thread(self._store.ensure_collection, vector_size=self._embedder.dimension)

        total = 0
        for batch in _batched(chunks, self._cfg.batch_size):
            vectors = await self._embedder.embed_texts([c.text for c in batch])
            points = []
            for c, v in zip(batch, vectors, strict=True):
                pid = _chunk_id(c)
                payload = {
                    "service_name": service_name,
                    "repo_local_dir": c.repo_local_dir,
                    "file_path": c.file_path,
                    "language": c.language,
                    "symbol": c.symbol or "",
                    "start_line": c.start_line,
                    "end_line": c.end_line,
                    "text": c.text,
                }
                points.append(PointStruct(id=pid, vector=v, payload=payload))
            await asyncio.to_thread(self._store.upsert_points, points)
            total += len(points)
        return total


def _chunk_id(c: CodeChunk) -> str:
    s = f"{c.repo_local_dir}:{c.file_path}:{c.start_line}:{c.end_line}:{c.symbol or ''}"
    return str(uuid.uuid5(uuid.NAMESPACE_DNS, s))


def _batched(items: list[CodeChunk], batch_size: int):
    for i in range(0, len(items), batch_size):
        yield items[i : i + batch_size]
