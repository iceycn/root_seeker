from __future__ import annotations

import hashlib
from dataclasses import dataclass
from typing import Protocol

from fastembed import TextEmbedding


class EmbeddingProvider(Protocol):
    @property
    def dimension(self) -> int: ...

    async def embed_texts(self, texts: list[str]) -> list[list[float]]: ...


@dataclass(frozen=True)
class FastEmbedConfig:
    model_name: str = "BAAI/bge-small-en-v1.5"
    cache_dir: str | None = None


class FastEmbedProvider:
    def __init__(self, cfg: FastEmbedConfig):
        kwargs: dict = {"model_name": cfg.model_name}
        if cfg.cache_dir is not None:
            kwargs["cache_dir"] = cfg.cache_dir
        self._model = TextEmbedding(**kwargs)
        self._dim = self._model.embedding_size

    @property
    def dimension(self) -> int:
        return int(self._dim)

    async def embed_texts(self, texts: list[str]) -> list[list[float]]:
        vectors = []
        for v in self._model.embed(texts):
            vectors.append([float(x) for x in v])
        return vectors


@dataclass(frozen=True)
class HashEmbeddingConfig:
    dimension: int = 384


class HashEmbeddingProvider:
    def __init__(self, cfg: HashEmbeddingConfig | None = None):
        self._dim = (cfg or HashEmbeddingConfig()).dimension

    @property
    def dimension(self) -> int:
        return self._dim

    async def embed_texts(self, texts: list[str]) -> list[list[float]]:
        out: list[list[float]] = []
        for t in texts:
            h = hashlib.sha256(t.encode("utf-8", errors="ignore")).digest()
            vec = [0.0] * self._dim
            for i, b in enumerate(h):
                vec[(i * 31) % self._dim] = (b - 128) / 128.0
            out.append(vec)
        return out

