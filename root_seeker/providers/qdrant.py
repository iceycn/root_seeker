from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from qdrant_client import QdrantClient
from qdrant_client.http.models import Distance, Filter, PointStruct, VectorParams


@dataclass(frozen=True)
class QdrantConfig:
    url: str = "http://127.0.0.1:6333"
    api_key: str | None = None
    collection: str = "code_chunks"


class QdrantVectorStore:
    def __init__(self, cfg: QdrantConfig):
        self._cfg = cfg
        self._client = QdrantClient(url=cfg.url, api_key=cfg.api_key)

    def ensure_collection(self, *, vector_size: int) -> None:
        if self._client.collection_exists(collection_name=self._cfg.collection):
            return
        self._client.create_collection(
            collection_name=self._cfg.collection,
            vectors_config=VectorParams(size=vector_size, distance=Distance.COSINE),
        )

    def upsert_points(self, points: list[PointStruct]) -> None:
        self._client.upsert(collection_name=self._cfg.collection, points=points)

    def search(
        self,
        *,
        vector: list[float],
        limit: int = 20,
        qfilter: Filter | None = None,
    ) -> list[dict[str, Any]]:
        response = self._client.query_points(
            collection_name=self._cfg.collection,
            query=vector,
            limit=limit,
            query_filter=qfilter,
            with_payload=True,
        )
        out: list[dict[str, Any]] = []
        for h in response.points:
            out.append({"score": float(h.score), "payload": h.payload or {}})
        return out

