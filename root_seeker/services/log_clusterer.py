"""日志聚类服务：将相似错误日志分组，每组抽样一条进行分析。尽量使用算法，减少 AI 调用。"""
from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass, field
from typing import Any, Protocol

from root_seeker.domain import IngestEvent


def _extract_error_text(raw: dict[str, Any] | IngestEvent) -> str:
    """从日志对象提取用于签名的文本。"""
    if isinstance(raw, IngestEvent):
        return raw.error_log or ""
    if isinstance(raw, dict):
        return str(raw.get("error_log") or raw.get("content") or "")
    return ""


def extract_fingerprint(text: str) -> str:
    """
    从错误日志文本提取指纹（模板化），用于相似问题分组。
    - 提取异常类型（如 NullPointerException）
    - 提取首行消息
    - 提取堆栈签名：at pkg.Class.method(File.java) 去掉行号
    """
    if not text or not text.strip():
        return ""
    lines = [ln.strip() for ln in text.split("\n") if ln.strip()]
    if not lines:
        return ""

    parts: list[str] = []

    # 首行：通常为 "ExceptionType: message" 或纯 message
    first = lines[0]
    if ":" in first:
        exc_type, rest = first.split(":", 1)
        exc_type = exc_type.strip().split(".")[-1]  # 取短类名
        parts.append(exc_type)
        # 消息首句，去掉可能变化的数字/ID
        msg = re.sub(r"\d+", "#", rest.strip())[:200]
        parts.append(msg)
    else:
        msg = re.sub(r"\d+", "#", first)[:200]
        parts.append(msg)

    # 堆栈：at pkg.Class.method(File.java:123) -> at pkg.Class.method(File.java)
    stack_sigs: list[str] = []
    for ln in lines[1:]:
        m = re.search(r"\bat\s+(\S+)\s*\(([^:)]+)(?::\d+)?\)", ln)
        if m:
            stack_sigs.append(f"{m.group(1)}({m.group(2)})")
        elif ln.startswith("at ") or " at " in ln:
            # 简化：at xxx.xxx.Class.method(File.java:123)
            simplified = re.sub(r":\d+\)", ")", ln)
            simplified = re.sub(r"\.java:\d+", ".java", simplified)
            stack_sigs.append(simplified[:150])
        if len(stack_sigs) >= 8:
            break
    parts.append("|".join(stack_sigs))
    return "\n".join(parts)


def fingerprint_hash(text: str) -> str:
    """对指纹文本做 SHA256 哈希。"""
    return hashlib.sha256(text.encode("utf-8", errors="ignore")).hexdigest()


class EmbeddingProvider(Protocol):
    @property
    def dimension(self) -> int: ...

    async def embed_texts(self, texts: list[str]) -> list[list[float]]: ...


def _cosine_similarity(a: list[float], b: list[float]) -> float:
    """余弦相似度，纯 Python 实现。"""
    dot = sum(x * y for x, y in zip(a, b))
    norm_a = sum(x * x for x in a) ** 0.5
    norm_b = sum(x * x for x in b) ** 0.5
    if norm_a < 1e-9 or norm_b < 1e-9:
        return 0.0
    return dot / (norm_a * norm_b)


class _UnionFind:
    """并查集，用于合并相似日志。"""

    def __init__(self, n: int) -> None:
        self.parent = list(range(n))

    def find(self, x: int) -> int:
        if self.parent[x] != x:
            self.parent[x] = self.find(self.parent[x])
        return self.parent[x]

    def union(self, x: int, y: int) -> None:
        px, py = self.find(x), self.find(y)
        if px != py:
            self.parent[px] = py


@dataclass
class LogClusterResult:
    """聚类结果。"""
    clusters: list[list[int]] = field(default_factory=list)  # 每簇的原始索引列表
    representatives: list[int] = field(default_factory=list)  # 每簇代表样本的索引
    events: list[IngestEvent] = field(default_factory=list)  # 原始事件列表
    method: str = "fingerprint"  # fingerprint | embedding


class LogClusterer:
    """
    日志聚类：将相似错误分组，每组抽样一条。
    优先使用指纹哈希（零 AI），可选 embedding 做更细粒度聚类。
    """

    def __init__(
        self,
        embedder: EmbeddingProvider | None = None,
        similarity_threshold: float = 0.88,
        max_logs_for_embedding: int = 2000,
    ) -> None:
        self.embedder = embedder
        self.similarity_threshold = similarity_threshold
        self.max_logs_for_embedding = max_logs_for_embedding

    async def cluster(self, events: list[IngestEvent]) -> LogClusterResult:
        """
        对日志列表聚类，返回每簇及代表样本索引。
        """
        if not events:
            return LogClusterResult(events=[])

        # 1. 指纹哈希分组（零 AI）
        fp_to_indices: dict[str, list[int]] = {}
        for i, ev in enumerate(events):
            text = ev.error_log or ""
            fp = extract_fingerprint(text)
            if not fp:
                fp = hashlib.sha256(text.encode("utf-8", errors="ignore")).hexdigest()
            h = fingerprint_hash(fp)
            fp_to_indices.setdefault(h, []).append(i)

        # 2. 可选：embedding 进一步合并相似簇
        if self.embedder and len(events) <= self.max_logs_for_embedding:
            texts = [_extract_error_text(ev) for ev in events]
            if texts:
                vectors = await self.embedder.embed_texts(texts)
                uf = _UnionFind(len(events))
                n = len(events)
                for i in range(n):
                    for j in range(i + 1, n):
                        if uf.find(i) == uf.find(j):
                            continue
                        sim = _cosine_similarity(vectors[i], vectors[j])
                        if sim >= self.similarity_threshold:
                            uf.union(i, j)
                # 按并查集重组簇
                cluster_map: dict[int, list[int]] = {}
                for i in range(n):
                    root = uf.find(i)
                    cluster_map.setdefault(root, []).append(i)
                clusters = list(cluster_map.values())
                method = "embedding"
            else:
                clusters = list(fp_to_indices.values())
                method = "fingerprint"
        else:
            clusters = list(fp_to_indices.values())
            method = "fingerprint"

        # 3. 每簇抽样一个代表（选 error_log 最长的，信息最全）
        representatives: list[int] = []
        for c in clusters:
            best = max(c, key=lambda idx: len(events[idx].error_log or ""))
            representatives.append(best)

        return LogClusterResult(
            clusters=clusters,
            representatives=representatives,
            events=events,
            method=method,
        )
