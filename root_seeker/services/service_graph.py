from __future__ import annotations

import json
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable

from root_seeker.config import RepoConfig
from root_seeker.domain import RelatedService


@dataclass(frozen=True)
class EdgeEvidence:
    caller: str
    callee: str
    evidence: list[str]


class ServiceGraph:
    def __init__(self, edges: list[EdgeEvidence]):
        self._edges = edges
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

    def to_json(self) -> list[dict]:
        return [{"caller": e.caller, "callee": e.callee, "evidence": e.evidence} for e in self._edges]

    @classmethod
    def from_json(cls, data: list[dict]) -> "ServiceGraph":
        edges = [
            EdgeEvidence(caller=str(d["caller"]), callee=str(d["callee"]), evidence=list(d.get("evidence") or []))
            for d in data
        ]
        return cls(edges)


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
                    break
                rel = str(p.relative_to(base))
                for callee, ev in _extract_callees_from_file(p, rel, known):
                    if callee == repo.service_name:
                        continue
                    key = (repo.service_name, callee)
                    edges.setdefault(key, [])
                    if len(edges[key]) < self._cfg.max_evidence_per_edge:
                        edges[key].append(ev)

        edge_list = [EdgeEvidence(caller=k[0], callee=k[1], evidence=v) for k, v in edges.items()]
        return ServiceGraph(edge_list)


def save_graph(graph: ServiceGraph, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(graph.to_json(), ensure_ascii=False, indent=2), encoding="utf-8")


def load_graph(path: Path) -> ServiceGraph | None:
    if not path.exists():
        return None
    data = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(data, list):
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
_FEIGN_RE = re.compile(r'@FeignClient\([^)]*name\s*=\s*"([^"]+)"')


def _extract_callees_from_file(
    path: Path, rel: str, known: dict[str, str]
) -> Iterable[tuple[str, str]]:
    try:
        lines = path.read_text(encoding="utf-8", errors="replace").splitlines()
    except Exception:
        return []

    out: list[tuple[str, str]] = []
    for i, line in enumerate(lines[:5000], start=1):
        for m in _URL_HOST_RE.finditer(line):
            host = m.group(1)
            svc = _normalize_host_to_service(host, known)
            if svc:
                out.append((svc, f"{rel}:{i} {line.strip()[:200]}"))
        m2 = _FEIGN_RE.search(line)
        if m2:
            svc = _normalize_host_to_service(m2.group(1), known)
            if svc:
                out.append((svc, f"{rel}:{i} {line.strip()[:200]}"))
    return out


def _normalize_host_to_service(host: str, known: dict[str, str]) -> str | None:
    host = host.strip()
    if not host:
        return None
    if ":" in host:
        host = host.split(":", 1)[0]
    if "/" in host:
        host = host.split("/", 1)[0]
    if host.endswith(".svc.cluster.local"):
        host = host.replace(".svc.cluster.local", "")
    if "." in host:
        host = host.split(".", 1)[0]
    if host in known:
        return known[host]
    if host.endswith("-service") and host in known:
        return known[host]
    return None
