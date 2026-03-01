from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from qdrant_client import QdrantClient
from qdrant_client.http.models import (
    Distance,
    FieldCondition,
    Filter,
    FilterSelector,
    MatchValue,
    PointStruct,
    VectorParams,
)


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

    def delete_points_by_file(
        self, *, service_name: str, file_path: str, repo_local_dir: str | None = None
    ) -> None:
        """删除指定服务、文件的所有向量点（用于增量索引时先删后增）。"""
        conditions = [
            FieldCondition(key="service_name", match=MatchValue(value=service_name)),
            FieldCondition(key="file_path", match=MatchValue(value=file_path)),
        ]
        if repo_local_dir:
            conditions.append(
                FieldCondition(key="repo_local_dir", match=MatchValue(value=repo_local_dir))
            )
        self._client.delete_points(
            collection_name=self._cfg.collection,
            points_selector=FilterSelector(filter=Filter(must=conditions)),
        )

    def delete_points_by_service(self, *, service_name: str) -> None:
        """删除指定服务的所有向量点（用于全量重置）。"""
        self._client.delete_points(
            collection_name=self._cfg.collection,
            points_selector=FilterSelector(
                filter=Filter(
                    must=[FieldCondition(key="service_name", match=MatchValue(value=service_name))]
                )
            ),
        )

    def delete_collection(self) -> None:
        """删除整个 collection（用于强制清除全部向量）。下次索引时会自动重建。"""
        if self._client.collection_exists(collection_name=self._cfg.collection):
            self._client.delete_collection(collection_name=self._cfg.collection)

    def count_points_by_service(self, *, service_name: str) -> int:
        """统计指定服务的向量点数，用于索引状态展示。"""
        if not self._client.collection_exists(collection_name=self._cfg.collection):
            return 0
        result = self._client.count(
            collection_name=self._cfg.collection,
            count_filter=Filter(
                must=[FieldCondition(key="service_name", match=MatchValue(value=service_name))]
            ),
        )
        return result.count

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

