"""依赖源码 MCP 工具：deps.fetch_java_sources、deps.index_dependency_sources。LSP 不可用时的兜底。"""

from __future__ import annotations

import json
from typing import Any, Dict

from root_seeker.mcp.protocol import ToolResult, ToolSchema
from root_seeker.mcp.tools.base import BaseTool
from root_seeker.services.dependency_sources import (
    DepCoordinate,
    MaterializedSourceRoot,
    fetch_java_sources,
    index_source_roots,
    materialize_maven_sources,
)
from root_seeker.services.external_deps import _as_dict
from root_seeker.services.router import ServiceRouter


class DepsFetchJavaSourcesTool(BaseTool):
    """deps.fetch_java_sources：获取 Java 依赖的源码坐标并物化到可读路径。"""

    def __init__(self, router: ServiceRouter):
        self._router = router

    @property
    def name(self) -> str:
        return "deps.fetch_java_sources"

    @property
    def schema(self) -> ToolSchema:
        return ToolSchema(
            name=self.name,
            description="获取 Java 项目依赖的源码坐标，并物化到 ~/.m2 中的 *-sources.jar。当 LSP 不可用时作为兜底，供 code.resolve_symbol 使用。",
            inputSchema={
                "type": "object",
                "properties": {
                    "project_root": {"type": "string"},
                    "repo_id": {"type": "string"},
                },
                "required": [],
            },
        )

    def _resolve_project_root(self, args: Dict[str, Any], context: Dict[str, Any] | None) -> str | None:
        if args.get("project_root"):
            return args["project_root"]
        repo_id = args.get("repo_id") or (context or {}).get("service_name")
        if repo_id:
            candidates = self._router.route(str(repo_id))
            if candidates:
                return candidates[0].local_dir
        return None

    async def run(self, args: Dict[str, Any], context: Dict[str, Any] | None = None) -> ToolResult:
        project_root = self._resolve_project_root(args, context)
        if not project_root:
            return ToolResult.error("缺少 project_root 或 repo_id", error_code="INVALID_PARAMS")
        try:
            coords = fetch_java_sources(project_root)
            materialized = materialize_maven_sources(coords)
            out = {
                "coordinates": _as_dict(coords),
                "materialized_sources": [
                    {"path": m.path, "coord": _as_dict(m.coord), "kind": m.kind}
                    for m in materialized
                ],
            }
            return ToolResult.text(json.dumps(out, ensure_ascii=False))
        except Exception as e:
            return ToolResult.error(f"deps.fetch_java_sources 执行失败: {e}", error_code="INTERNAL_ERROR")


class DepsIndexDependencySourcesTool(BaseTool):
    """deps.index_dependency_sources：索引已物化的依赖源码。"""

    def __init__(self, router: ServiceRouter):
        self._router = router

    @property
    def name(self) -> str:
        return "deps.index_dependency_sources"

    @property
    def schema(self) -> ToolSchema:
        return ToolSchema(
            name=self.name,
            description="对 deps.fetch_java_sources 返回的 materialized_sources 建立索引，供 code.resolve_symbol 使用。",
            inputSchema={
                "type": "object",
                "properties": {
                    "materialized_sources": {
                        "type": "array",
                        "description": "deps.fetch_java_sources 返回的 materialized_sources",
                    },
                },
                "required": ["materialized_sources"],
            },
        )

    async def run(self, args: Dict[str, Any], context: Dict[str, Any] | None = None) -> ToolResult:
        ms = args.get("materialized_sources")
        if not ms:
            return ToolResult.error("缺少 materialized_sources", error_code="INVALID_PARAMS")
        roots = []
        for m in ms:
            if isinstance(m, dict):
                path = m.get("path")
                coord = m.get("coord", {})
                c = DepCoordinate(
                    group_id=coord.get("group_id"),
                    artifact_id=coord.get("artifact_id"),
                    version=coord.get("version"),
                )
                roots.append(MaterializedSourceRoot(coord=c, path=path or "", kind=m.get("kind", "maven_sources")))
        try:
            idx = index_source_roots(roots)
            return ToolResult.text(json.dumps(idx, ensure_ascii=False))
        except Exception as e:
            return ToolResult.error(f"deps.index_dependency_sources 执行失败: {e}", error_code="INTERNAL_ERROR")
