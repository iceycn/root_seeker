"""外部依赖识别 MCP 工具：deps.parse_external、deps.diff_declared_vs_resolved。"""

from __future__ import annotations

import json
from typing import Any, Callable, Dict

from root_seeker.mcp.protocol import ToolResult, ToolSchema
from root_seeker.mcp.tools.base import BaseTool
from root_seeker.services.external_deps import (
    DeclaredDeps,
    DriftReport,
    _as_dict,
    diff_declared_vs_resolved,
    parse_external,
    scan_binaries,
)
from root_seeker.services.router import ServiceRouter


class DepsParseExternalTool(BaseTool):
    """deps.parse_external：解析构建文件，输出结构化依赖画像。"""

    def __init__(self, router: ServiceRouter):
        self._router = router

    @property
    def name(self) -> str:
        return "deps.parse_external"

    @property
    def schema(self) -> ToolSchema:
        return ToolSchema(
            name=self.name,
            description="解析项目构建文件（pom.xml/build.gradle/requirements.txt/pyproject.toml），输出结构化依赖画像。默认先走静态解析；版本变量无法解析时再考虑 cmd.run_build_analysis。",
            inputSchema={
                "type": "object",
                "properties": {
                    "project_root": {"type": "string", "description": "项目根目录绝对路径"},
                    "repo_id": {"type": "string", "description": "可选，服务名/仓库标识，与 project_root 二选一，用于从路由解析 local_dir"},
                    "manifest_file": {"type": "string", "description": "可选，指定构建文件如 pom.xml、requirements.txt"},
                },
                "required": [],
            },
        )

    def _resolve_project_root(self, args: Dict[str, Any], context: Dict[str, Any] | None) -> str | None:
        """解析 project_root：优先 args，否则从 repo_id 路由。"""
        project_root = args.get("project_root")
        if project_root and isinstance(project_root, str):
            return project_root
        repo_id = args.get("repo_id") or (context or {}).get("service_name")
        if repo_id:
            candidates = self._router.route(str(repo_id))
            if candidates:
                return candidates[0].local_dir
        return None

    async def run(self, args: Dict[str, Any], context: Dict[str, Any] | None = None) -> ToolResult:
        project_root = self._resolve_project_root(args, context)
        if not project_root:
            return ToolResult.error(
                "缺少 project_root 或 repo_id（且无法从 context 解析）",
                error_code="INVALID_PARAMS",
            )
        manifest_file = args.get("manifest_file")
        try:
            result = parse_external(project_root, manifest_file)
            out = {
                "ecosystem": result.ecosystem,
                "direct_dependencies": _as_dict(result.direct_dependencies),
                "declared_variables": _as_dict(result.declared_variables),
                "risk_flags": result.risk_flags,
                "manifest_path": result.manifest_path,
            }
            return ToolResult.text(json.dumps(out, ensure_ascii=False))
        except Exception as e:
            return ToolResult.error(f"deps.parse_external 执行失败: {e}", error_code="INTERNAL_ERROR")


class DepsDiffDeclaredVsResolvedTool(BaseTool):
    """deps.diff_declared_vs_resolved：对比声明与解析的依赖，输出漂移项。"""

    @property
    def name(self) -> str:
        return "deps.diff_declared_vs_resolved"

    @property
    def schema(self) -> ToolSchema:
        return ToolSchema(
            name=self.name,
            description="对比 deps.parse_external 的声明依赖与 cmd.run_build_analysis 的解析依赖，输出漂移项（声明有但未解析、解析有但未声明、版本不一致）。",
            inputSchema={
                "type": "object",
                "properties": {
                    "declared": {
                        "type": "object",
                        "description": "deps.parse_external 的输出或 {direct_dependencies: [...]}",
                    },
                    "resolved": {
                        "type": "array",
                        "description": "cmd.run_build_analysis 的 resolved_dependencies",
                    },
                },
                "required": ["declared", "resolved"],
            },
        )

    async def run(self, args: Dict[str, Any], context: Dict[str, Any] | None = None) -> ToolResult:
        declared = args.get("declared")
        resolved = args.get("resolved")
        if declared is None or resolved is None:
            return ToolResult.error("缺少 declared 或 resolved", error_code="INVALID_PARAMS")
        try:
            report = diff_declared_vs_resolved(declared, resolved)
            out = {
                "declared_not_resolved": _as_dict(report.declared_not_resolved),
                "resolved_not_declared": _as_dict(report.resolved_not_declared),
                "version_mismatches": [
                    {
                        "kind": i.kind,
                        "message": i.message,
                        "declared": _as_dict(i.declared),
                        "resolved": _as_dict(i.resolved),
                    }
                    for i in report.version_mismatches
                ],
            }
            return ToolResult.text(json.dumps(out, ensure_ascii=False))
        except Exception as e:
            return ToolResult.error(f"deps.diff_declared_vs_resolved 执行失败: {e}", error_code="INTERNAL_ERROR")


class DepsScanBinariesTool(BaseTool):
    """deps.scan_binaries：识别本地 jar/whl/so/dylib 等二进制依赖作为额外证据。"""

    def __init__(self, router: ServiceRouter):
        self._router = router

    @property
    def name(self) -> str:
        return "deps.scan_binaries"

    @property
    def schema(self) -> ToolSchema:
        return ToolSchema(
            name=self.name,
            description="扫描 project_root 下的二进制依赖（*.jar、*.whl、*.so、*.dylib 等）作为额外证据，用于依赖冲突分析。",
            inputSchema={
                "type": "object",
                "properties": {
                    "project_root": {"type": "string"},
                    "repo_id": {"type": "string"},
                    "patterns": {"type": "array", "items": {"type": "string"}, "description": "可选，默认 [*.jar, *.whl, *.so, *.dylib]"},
                    "max_per_kind": {"type": "integer", "description": "每种类型最多返回数量，默认 50"},
                },
                "required": [],
            },
        )

    def _resolve_project_root(self, args: Dict[str, Any], context: Dict[str, Any] | None) -> str | None:
        project_root = args.get("project_root")
        if project_root and isinstance(project_root, str):
            return project_root
        repo_id = args.get("repo_id") or (context or {}).get("service_name")
        if repo_id:
            candidates = self._router.route(str(repo_id))
            if candidates:
                return candidates[0].local_dir
        return None

    async def run(self, args: Dict[str, Any], context: Dict[str, Any] | None = None) -> ToolResult:
        project_root = self._resolve_project_root(args, context)
        if not project_root:
            return ToolResult.error(
                "缺少 project_root 或 repo_id",
                error_code="INVALID_PARAMS",
            )
        try:
            patterns = args.get("patterns") or ["*.jar", "*.whl", "*.so", "*.dylib"]
            max_per_kind = int(args.get("max_per_kind") or 50)
            bins = scan_binaries(project_root, patterns=patterns, max_per_kind=max_per_kind)
            out = [{"path": b.path, "kind": b.kind, "size_bytes": b.size_bytes} for b in bins]
            return ToolResult.text(json.dumps({"binaries": out, "count": len(out)}, ensure_ascii=False))
        except Exception as e:
            return ToolResult.error(f"deps.scan_binaries 执行失败: {e}", error_code="INTERNAL_ERROR")
