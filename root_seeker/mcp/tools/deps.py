"""依赖关系类 MCP 工具：deps.get_graph。"""

from __future__ import annotations

import asyncio
import json
import logging
from pathlib import Path
from typing import Any, Callable, Dict

from root_seeker.mcp.protocol import ToolResult, ToolSchema
from root_seeker.mcp.tools.base import BaseTool
from root_seeker.services.service_graph import ServiceGraph

logger = logging.getLogger(__name__)

SCOPE_METHOD_TIMEOUT = 30
SCOPE_METHOD_MAX_DEPTH = 2


class DepsGraphTool(BaseTool):
    """deps.get_graph：基于 ServiceGraph 与 CallGraphExpander 返回依赖拓扑。"""

    def __init__(
        self,
        graph_loader: Callable[[], ServiceGraph | None],
        call_graph_expander=None,
        router=None,
    ):
        self._graph_loader = graph_loader
        self._call_graph_expander = call_graph_expander
        self._router = router

    @property
    def name(self) -> str:
        return "deps.get_graph"

    @property
    def schema(self) -> ToolSchema:
        return ToolSchema(
            name=self.name,
            description="获取服务/方法依赖拓扑。scope=service 返回服务级依赖（毫秒级）；scope=method 触发代码扫描（秒级）。",
            inputSchema={
                "type": "object",
                "properties": {
                    "scope": {"type": "string", "enum": ["service", "method"], "description": "service(默认)|method"},
                    "target": {"type": "string", "description": "服务名或方法签名"},
                    "direction": {"type": "string", "enum": ["upstream", "downstream", "both"], "description": "依赖方向"},
                    "depth": {"type": "integer", "description": "深度，默认 1"},
                },
                "required": ["target"],
            },
        )

    async def run(self, args: Dict[str, Any], context: Dict[str, Any] | None = None) -> ToolResult:
        target = args.get("target")
        if not target:
            return ToolResult.error("缺少必填参数 target")

        scope = args.get("scope") or "service"
        direction = args.get("direction") or "both"
        depth = int(args.get("depth") or 1)

        if scope == "method":
            return await self._run_scope_method(target, direction, depth)

        graph = self._graph_loader() if self._graph_loader else None
        if graph is None:
            return ToolResult.text(
                json.dumps({"nodes": [], "edges": [], "message": "依赖图未加载"}, ensure_ascii=False)
            )

        nodes_set = {target}
        edges = []

        if direction in ("upstream", "both"):
            for rel in graph.upstream_of(target):
                nodes_set.add(rel.service_name)
                edges.append({"from": rel.service_name, "to": target, "relation": "upstream"})
        if direction in ("downstream", "both"):
            for rel in graph.downstream_of(target):
                nodes_set.add(rel.service_name)
                edges.append({"from": target, "to": rel.service_name, "relation": "downstream"})

        nodes = [{"id": n, "label": n} for n in nodes_set]
        out = {"nodes": nodes, "edges": edges}
        if hasattr(graph, "_scan_meta") and graph._scan_meta:
            meta = graph._scan_meta
            if meta.get("risk_flags"):
                out["risk_flags"] = meta["risk_flags"]
            if meta.get("read_failures"):
                out["read_failures"] = meta["read_failures"]
            if meta.get("scan_truncated_repo"):
                out["scan_truncated_repo"] = meta["scan_truncated_repo"]
        return ToolResult.text(json.dumps(out, ensure_ascii=False))

    async def _run_scope_method(
        self, target: str, direction: str, depth: int
    ) -> ToolResult:
        """scope=method：触发代码扫描，返回方法级依赖（限制 depth<=2、超时）。"""
        depth = min(int(depth or 1), SCOPE_METHOD_MAX_DEPTH)
        expander = self._call_graph_expander
        if not expander or not getattr(expander, "_zoekt_client", None):
            return ToolResult.text(
                json.dumps(
                    {"nodes": [], "edges": [], "message": "scope=method 需要 call_graph_expansion 与 zoekt 配置"},
                    ensure_ascii=False,
                )
            )
        if not self._router:
            return ToolResult.text(
                json.dumps(
                    {"nodes": [], "edges": [], "message": "scope=method 需要 router 配置"},
                    ensure_ascii=False,
                )
            )

        # 解析 target：ClassName.methodName 或 service-name.methodName
        parts = target.split(".", 1)
        service_hint = parts[0] if len(parts) > 1 else target
        method_name = parts[1] if len(parts) > 1 else target
        class_name = parts[0] if len(parts) > 1 and parts[0][0].isupper() else None

        candidates = self._router.route(service_hint)
        if not candidates:
            candidates = self._router.infer_from_error_log(method_name, service_hint)
        if not candidates:
            return ToolResult.text(
                json.dumps(
                    {"nodes": [], "edges": [], "message": f"未找到 target={target} 对应的仓库"},
                    ensure_ascii=False,
                )
            )

        repo = candidates[0]
        repo_local_dir = repo.local_dir
        zoekt = expander._zoekt_client

        try:
            result = await asyncio.wait_for(
                self._scan_method_deps(
                    expander=expander,
                    zoekt=zoekt,
                    repo_local_dir=repo_local_dir,
                    method_name=method_name,
                    class_name=class_name,
                    direction=direction,
                    depth=depth,
                ),
                timeout=SCOPE_METHOD_TIMEOUT,
            )
            return ToolResult.text(json.dumps(result, ensure_ascii=False))
        except asyncio.TimeoutError:
            logger.warning("[DepsGraphTool] scope=method 超时")
            return ToolResult.text(
                json.dumps(
                    {"nodes": [], "edges": [], "message": "scope=method 扫描超时，请使用 scope=service"},
                    ensure_ascii=False,
                )
            )
        except Exception as e:
            logger.exception("[DepsGraphTool] scope=method 失败: %s", e)
            return ToolResult.text(
                json.dumps(
                    {"nodes": [], "edges": [], "message": f"scope=method 执行失败: {e}"},
                    ensure_ascii=False,
                )
            )

    async def _scan_method_deps(
        self,
        *,
        expander,
        zoekt,
        repo_local_dir: str,
        method_name: str,
        class_name: str | None,
        direction: str,
        depth: int,
    ) -> dict:
        """扫描方法级依赖：搜索方法定义，解析调用关系。"""
        base = Path(repo_local_dir)
        if not base.exists():
            return {"nodes": [], "edges": [], "message": "仓库目录不存在"}

        center = f"{class_name}.{method_name}" if class_name else method_name
        query = f"{class_name} {method_name}" if class_name else method_name
        hits = await zoekt.search(query=query, max_matches=10)
        if not hits:
            return {"nodes": [], "edges": [], "message": f"未找到方法 {method_name}"}

        nodes_set = {center}
        edges_list: list[dict] = []
        seen_files: set[str] = set()

        for hit in hits[:5]:
            if not hit.file_path or hit.file_path in seen_files:
                continue
            file_path = hit.file_path.lstrip("/")
            path = base / file_path
            if not path.exists() or not path.is_file():
                continue
            seen_files.add(file_path)
            try:
                code = path.read_text(encoding="utf-8", errors="replace")
            except Exception:
                continue
            calls = await expander._extract_method_calls(code, file_path, repo_local_dir)
            for c in calls[:10]:
                callee = f"{c.class_name}.{c.method_name}" if c.class_name else c.method_name
                if not callee:
                    callee = c.method_name
                nodes_set.add(callee)
                if direction in ("downstream", "both"):
                    edges_list.append({"from": center, "to": callee, "relation": "calls"})
                if direction in ("upstream", "both") and callee != center:
                    edges_list.append({"from": callee, "to": center, "relation": "called_by"})

        nodes = [{"id": n, "label": n} for n in nodes_set]
        return {"nodes": nodes, "edges": edges_list}
