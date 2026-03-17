from __future__ import annotations

import json
import logging
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable

from root_seeker.config import RepoConfig
from root_seeker.domain import RelatedService

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class EdgeEvidence:
    caller: str
    callee: str
    evidence: list[str]
    confidence: float = 1.0  # 1.0=高置信度, 0.5=低置信度(占位符等)


class ServiceGraph:
    def __init__(self, edges: list[EdgeEvidence], scan_meta: dict | None = None):
        self._edges = edges
        self._scan_meta = scan_meta or {}
        self._by_caller: dict[str, list[EdgeEvidence]] = {}
        self._by_callee: dict[str, list[EdgeEvidence]] = {}
        for e in edges:
            self._by_caller.setdefault(e.caller, []).append(e)
            self._by_callee.setdefault(e.callee, []).append(e)

    def downstream_of(self, service_name: str) -> list[RelatedService]:
        out: list[RelatedService] = []
        for e in self._by_caller.get(service_name, []):
            out.append(RelatedService(service_name=e.callee, relation="downstream", evidence=e.evidence[:5]))
        return out

    def upstream_of(self, service_name: str) -> list[RelatedService]:
        out: list[RelatedService] = []
        for e in self._by_callee.get(service_name, []):
            out.append(RelatedService(service_name=e.caller, relation="upstream", evidence=e.evidence[:5]))
        return out

    def to_json(self) -> dict:
        edges = [{"caller": e.caller, "callee": e.callee, "evidence": e.evidence} for e in self._edges]
        out: dict = {"edges": edges}
        if self._scan_meta:
            out["meta"] = self._scan_meta
        return out

    @classmethod
    def from_json(cls, data: list[dict] | dict) -> "ServiceGraph":
        if isinstance(data, list):
            edges = [
                EdgeEvidence(caller=str(d["caller"]), callee=str(d["callee"]), evidence=list(d.get("evidence") or []))
                for d in data
            ]
            return cls(edges)
        edges_data = data.get("edges", data)
        edges = [
            EdgeEvidence(caller=str(d["caller"]), callee=str(d["callee"]), evidence=list(d.get("evidence") or []))
            for d in edges_data
        ]
        return cls(edges, scan_meta=data.get("meta"))


@dataclass(frozen=True)
class ServiceGraphConfig:
    max_files_per_repo: int = 30_000
    max_evidence_per_edge: int = 12


class ServiceGraphBuilder:
    def __init__(self, cfg: ServiceGraphConfig | None = None):
        self._cfg = cfg or ServiceGraphConfig()

    def build(self, repos: list[RepoConfig]) -> ServiceGraph:
        known = _build_known_services(repos)
        edges: dict[tuple[str, str], list[str]] = {}

        scan_meta: dict = {}
        for repo in repos:
            base = Path(repo.local_dir)
            if not base.exists():
                continue

            file_count = 0
            for p in base.rglob("*"):
                if not p.is_file():
                    continue
                if p.suffix not in {".py", ".java", ".yml", ".yaml", ".properties"} and p.name not in {
                    "pom.xml",
                    "build.gradle",
                }:
                    continue
                file_count += 1
                if file_count > self._cfg.max_files_per_repo:
                    scan_meta["risk_flags"] = scan_meta.get("risk_flags", []) + ["scan_truncated"]
                    scan_meta["scan_truncated_repo"] = repo.service_name
                    logger.info("[ServiceGraph] 仓库 %s 文件数超限(%d)，扫描截断", repo.service_name, file_count)
                    break
                rel = str(p.relative_to(base))
                for callee, ev, conf in _extract_callees_from_file(p, rel, known, scan_meta, repo.service_name):
                    if callee == repo.service_name:
                        continue
                    key = (repo.service_name, callee)
                    if key not in edges:
                        edges[key] = []
                    if len(edges[key]) < self._cfg.max_evidence_per_edge:
                        edges[key].append((ev, conf))

        edge_list = [
            EdgeEvidence(caller=k[0], callee=k[1], evidence=[e[0] for e in v], confidence=max((x[1] for x in v), default=1.0))
            for k, v in edges.items()
        ]
        return ServiceGraph(edge_list, scan_meta=scan_meta if scan_meta else None)


def save_graph(graph: ServiceGraph, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(graph.to_json(), ensure_ascii=False, indent=2), encoding="utf-8")


def load_graph(path: Path) -> ServiceGraph | None:
    if not path.exists():
        return None
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError) as e:
        logger.warning("[ServiceGraph] 加载依赖图失败: %s", e)
        return None
    if not isinstance(data, (list, dict)):
        return None
    return ServiceGraph.from_json(data)


def _build_known_services(repos: list[RepoConfig]) -> dict[str, str]:
    mapping: dict[str, str] = {}
    for r in repos:
        mapping[r.service_name] = r.service_name
        for a in r.repo_aliases:
            mapping[a] = r.service_name
    return mapping


_URL_HOST_RE = re.compile(r"https?://([A-Za-z0-9.-]+)")
_FEIGN_NAME_RE = re.compile(r'@FeignClient\([^)]*name\s*=\s*"([^"]+)"')
_FEIGN_VALUE_RE = re.compile(r'@FeignClient\s*\(\s*value\s*=\s*"([^"]+)"')
_FEIGN_URL_RE = re.compile(r'@FeignClient\s*\([^)]*url\s*=\s*"([^"]+)"')
_LB_SERVICE_RE = re.compile(r"lb://([A-Za-z0-9.-]+)")
_PLACEHOLDER_RE = re.compile(r"\$\{([^}:]+)[^}]*\}")  # ${xxx} 占位符，低置信度


def _extract_callees_from_file(
    path: Path, rel: str, known: dict[str, str],
    scan_meta: dict | None = None,
    repo_name: str = "",
) -> Iterable[tuple[str, str, float]]:
    """提取被调用服务，返回 (callee, evidence, confidence)。读取失败时写入 scan_meta 可解释。"""
    try:
        lines = path.read_text(encoding="utf-8", errors="replace").splitlines()
    except Exception as e:
        logger.debug("[ServiceGraph] 读取文件失败 %s: %s", rel, type(e).__name__)
        if scan_meta is not None:
            failures = scan_meta.setdefault("read_failures", [])
            if len(failures) < 20:  # 限制数量
                failures.append({"repo": repo_name, "file": rel, "error": type(e).__name__})
        return []

    out: list[tuple[str, str, float]] = []
    for i, line in enumerate(lines[:5000], start=1):
        ev = f"{rel}:{i} {line.strip()[:200]}"
        for m in _URL_HOST_RE.finditer(line):
            svc, conf = _host_to_callee_with_confidence(m.group(1), known)
            if svc:
                out.append((svc, ev, conf))
        for m in (_FEIGN_NAME_RE.search(line), _FEIGN_VALUE_RE.search(line), _FEIGN_URL_RE.search(line)):
            if m:
                svc, conf = _host_to_callee_with_confidence(m.group(1), known)
                if svc:
                    out.append((svc, ev, conf))
        for m in _LB_SERVICE_RE.finditer(line):
            svc, conf = _host_to_callee_with_confidence(m.group(1), known)
            if svc:
                out.append((svc, ev, conf))
        for m in _PLACEHOLDER_RE.finditer(line):
            placeholder = m.group(1)
            svc, _ = _host_to_callee_with_confidence(placeholder.replace("_", "-"), known)
            if svc:
                out.append((svc, ev, 0.5))
    return out


def _normalize_host(host: str) -> str:
    """规范化 host 为服务名形式。"""
    host = host.strip()
    if ":" in host:
        host = host.split(":", 1)[0]
    if "/" in host:
        host = host.split("/", 1)[0]
    if host.endswith(".svc.cluster.local"):
        host = host.replace(".svc.cluster.local", "")
    if "." in host:
        host = host.split(".", 1)[0]
    return host


def _normalize_host_to_service(host: str, known: dict[str, str]) -> str | None:
    """已知服务映射；未知则返回 None（由调用方决定是否产生低置信度边）。"""
    h = _normalize_host(host)
    if not h:
        return None
    if h in known:
        return known[h]
    if h.endswith("-service") and h in known:
        return known[h]
    return None


def _host_to_callee_with_confidence(host: str, known: dict[str, str]) -> tuple[str | None, float]:
    """返回 (callee, confidence)。已知服务 1.0；未知服务返回规范化 host 作为 callee、0.5 置信度。"""
    h = _normalize_host(host)
    if not h:
        return None, 0.0
    if h in known:
        return known[h], 1.0
    if h.endswith("-service") and h in known:
        return known[h], 1.0
    return h, 0.5  # 未知服务，低置信度边，供报告中可解释
