"""
可替换组件的 Protocol 定义，便于后续扩展多种向量库、切分器、词法检索实现。
当前 QdrantVectorStore、TreeSitterChunker、ZoektClient 均符合对应 Protocol，
后续可增加 kind 配置与工厂，按配置选择实现（如 Milvus、OpenGrok 等）。
"""
from __future__ import annotations

from typing import Any, Protocol, runtime_checkable


@runtime_checkable
class VectorStoreProtocol(Protocol):
    """向量存储可替换协议：当前由 QdrantVectorStore 实现，后续可接入 Milvus、pgvector 等。"""

    async def upsert(
        self,
        *,
        collection: str | None,
        points: list[dict[str, Any]],
        batch_size: int = 64,
    ) -> int:
        ...

    async def search(
        self,
        *,
        collection: str | None,
        vector: list[float],
        limit: int = 12,
        filter_conditions: dict[str, Any] | None = None,
    ) -> list[dict[str, Any]]:
        ...


@runtime_checkable
class ChunkerProtocol(Protocol):
    """代码切分可替换协议：当前由 TreeSitterChunker 实现，后续可接入其他切分策略。"""

    def chunk_repo(self, repo_local_dir: str, language_hints: list[str] | None = None) -> list[Any]:
        """对仓库目录进行切分，返回代码块列表（含 file_path、start_line、end_line、text 等）。"""
        ...


@runtime_checkable
class LexicalSearchProtocol(Protocol):
    """词法/符号检索可替换协议：当前由 ZoektClient 实现，后续可接入 OpenGrok 等。"""

    async def search(self, query: str) -> list[Any]:
        """按查询字符串检索，返回命中列表（含 repo、file_path、line_number、preview 等）。"""
        ...
