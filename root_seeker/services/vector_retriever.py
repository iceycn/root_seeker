from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass
from typing import Any

from qdrant_client.http.models import FieldCondition, Filter, MatchValue

from root_seeker.providers.embedding import EmbeddingProvider
from root_seeker.providers.qdrant import QdrantVectorStore

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class VectorSearchConfig:
    top_k: int = 12


class VectorRetriever:
    def __init__(
        self, *, cfg: VectorSearchConfig, embedder: EmbeddingProvider, store: QdrantVectorStore
    ):
        self._cfg = cfg
        self._embedder = embedder
        self._store = store

    async def search(
        self,
        *,
        query: str,
        service_name: str | None = None,
        repo_local_dir: str | None = None,
    ) -> list[dict[str, Any]]:
        logger.debug(f"[VectorRetriever] 开始向量检索，query长度={len(query)}, service={service_name}, repo={repo_local_dir}, top_k={self._cfg.top_k}")
        try:
            vectors = await self._embedder.embed_texts([query])
            qfilter = _build_filter(service_name=service_name, repo_local_dir=repo_local_dir)
            results = await asyncio.to_thread(
                self._store.search, vector=vectors[0], limit=self._cfg.top_k, qfilter=qfilter
            )
            logger.info(f"[VectorRetriever] 向量检索完成，返回 {len(results)} 个结果")
            return results
        except Exception as e:
            logger.error(f"[VectorRetriever] 向量检索失败：{e}", exc_info=True)
            raise


def _build_filter(*, service_name: str | None, repo_local_dir: str | None) -> Filter | None:
    conditions = []
    if service_name:
        conditions.append(FieldCondition(key="service_name", match=MatchValue(value=service_name)))
    if repo_local_dir:
        conditions.append(FieldCondition(key="repo_local_dir", match=MatchValue(value=repo_local_dir)))
    if not conditions:
        return None
    return Filter(must=conditions)
