from __future__ import annotations

import re
from dataclasses import dataclass

from root_seeker.config import RepoConfig
from root_seeker.domain import CandidateRepo


def _normalize_service_name(raw: str) -> str:
    """
    归一化服务名，便于匹配。
    - K8s pod 名如 bs-integration-7d8f9c-x2k3m → bs-integration
    - 保留 bs-integration-1 等形式（多实例）
    """
    s = (raw or "").strip()
    if not s:
        return s
    # 去掉 K8s deployment hash 后缀：-7d8f9c-x2k3m 或 -7d8f9c
    m = re.match(r"^(.+?)-[a-z0-9]{5,}(?:-[a-z0-9]{5})?$", s)
    if m:
        base = m.group(1)
        # 若 base 已是 xxx-数字（如 bs-integration-1），保留
        if re.search(r"-\d+$", base):
            return base
        return base
    return s


def _service_name_candidates(raw: str) -> list[str]:
    """生成用于匹配的候选 service_name，按优先级排序。"""
    normalized = _normalize_service_name(raw)
    candidates = [raw, normalized] if raw != normalized else [raw]
    # 前缀候选：bs-integration-1 → [bs-integration-1, bs-integration]
    if "-" in normalized:
        parts = normalized.rsplit("-", 1)
        if len(parts) == 2 and parts[1].isdigit():
            candidates.append(parts[0])
    return list(dict.fromkeys(candidates))


@dataclass(frozen=True)
class RepoCatalog:
    repos: list[RepoConfig]

    def find_by_service_name(self, service_name: str) -> list[RepoConfig]:
        matches: list[RepoConfig] = []
        for r in self.repos:
            if r.service_name == service_name:
                matches.append(r)
                continue
            if service_name in r.repo_aliases:
                matches.append(r)
        return matches


class ServiceRouter:
    def __init__(self, catalog: RepoCatalog):
        self._catalog = catalog

    def refresh_catalog(self, repos: list[RepoConfig]) -> None:
        """刷新仓库目录，供配置变更通知后使用。"""
        self._catalog = RepoCatalog(repos=repos)

    def route(self, service_name: str) -> list[CandidateRepo]:
        # 1. 精确匹配（含 repo_aliases）
        for candidate in _service_name_candidates(service_name):
            repos = self._catalog.find_by_service_name(candidate)
            if repos:
                return [
                    CandidateRepo(
                        service_name=r.service_name,
                        local_dir=r.local_dir,
                        git_url=r.git_url,
                        confidence=1.0 if candidate == service_name else 0.9,
                        evidence=["explicit_mapping" if candidate == service_name else f"normalized:{service_name}→{candidate}"],
                    )
                    for r in repos
                ]

        # 2. 前缀匹配：config 的 service_name 是输入的前缀（如 bs-integration 匹配 bs-integration-1）
        for r in self._catalog.repos:
            if service_name.startswith(r.service_name + "-") or service_name.startswith(r.service_name + "_"):
                return [
                    CandidateRepo(
                        service_name=r.service_name,
                        local_dir=r.local_dir,
                        git_url=r.git_url,
                        confidence=0.85,
                        evidence=[f"prefix_match:{service_name}→{r.service_name}"],
                    )
                ]

        # 3. 启发式：service_name 出现在 git_url 或 local_dir
        inferred: list[CandidateRepo] = []
        for r in self._catalog.repos:
            if service_name in r.git_url or service_name in r.local_dir:
                inferred.append(
                    CandidateRepo(
                        service_name=r.service_name,
                        local_dir=r.local_dir,
                        git_url=r.git_url,
                        confidence=0.6,
                        evidence=["heuristic: service_name matches git_url/local_dir"],
                    )
                )
            # 归一化后的候选也参与启发式
            for c in _service_name_candidates(service_name):
                if c != service_name and (c in r.git_url or c in r.local_dir):
                    inferred.append(
                        CandidateRepo(
                            service_name=r.service_name,
                            local_dir=r.local_dir,
                            git_url=r.git_url,
                            confidence=0.65,
                            evidence=[f"heuristic: normalized {c} matches git_url/local_dir"],
                        )
                    )

        inferred.sort(key=lambda x: x.confidence, reverse=True)
        return inferred[:5]

    def infer_from_error_log(self, error_log: str, fallback_service_name: str) -> list[CandidateRepo]:
        """
        从错误日志内容推断可能的 service_name，用于路由失败时的兜底。
        提取 Java 包名、路径等与 config 中的 service_name 做模糊匹配。
        """
        if not error_log or not self._catalog.repos:
            return []

        # 提取 Java 包名片段：net.coolcollege.incentive.xxx → incentive
        tokens: set[str] = set()
        for m in re.finditer(r"\b(?:net|com|cn)\.coolcollege\.([a-zA-Z0-9_.-]+)", error_log):
            pkg = m.group(1).split(".")[0].replace("_", "-")
            if len(pkg) >= 3:
                tokens.add(pkg)
        for m in re.finditer(r"([a-zA-Z0-9_-]+)-api\b", error_log):
            tokens.add(m.group(1))
        for m in re.finditer(r"\b([a-zA-Z0-9_-]+)-service\b", error_log):
            tokens.add(m.group(1))

        inferred: list[CandidateRepo] = []
        seen: set[str] = set()
        for r in self._catalog.repos:
            if r.service_name in seen:
                continue
            sn = r.service_name.lower()
            for t in tokens:
                t_lower = t.lower()
                if t_lower in sn or sn in t_lower:
                    inferred.append(
                        CandidateRepo(
                            service_name=r.service_name,
                            local_dir=r.local_dir,
                            git_url=r.git_url,
                            confidence=0.7,
                            evidence=[f"inferred_from_error_log: package/token '{t}' matches {r.service_name}"],
                        )
                    )
                    seen.add(r.service_name)
                    break

        inferred.sort(key=lambda x: x.confidence, reverse=True)
        return inferred[:3]

