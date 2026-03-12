"""索引状态类 MCP 工具：index.get_status。"""

from __future__ import annotations

import asyncio
import json
from typing import Any, Dict

from root_seeker.mcp.protocol import ToolResult, ToolSchema
from root_seeker.mcp.tools.base import BaseTool


class IndexStatusTool(BaseTool):
    """index.get_status：返回 Qdrant/Zoekt 索引状态。"""

    def __init__(self, qstore, zoekt_client, router=None):
        self._qstore = qstore
        self._zoekt = zoekt_client
        self._router = router

    @property
    def name(self) -> str:
        return "index.get_status"

    @property
    def schema(self) -> ToolSchema:
        return ToolSchema(
            name=self.name,
            description="获取各仓库的 Qdrant 与 Zoekt 索引状态。可选 service_name 限定单个仓库。",
            inputSchema={
                "type": "object",
                "properties": {
                    "service_name": {"type": "string", "description": "可选，限定单个服务/仓库"},
                },
                "required": [],
            },
        )

    async def run(self, args: Dict[str, Any], context: Dict[str, Any] | None = None) -> ToolResult:
        repos_to_check = []
        if self._router is not None:
            sn = args.get("service_name")
            if sn:
                candidates = self._router.route(str(sn))
                if candidates:
                    repos_to_check = [c.service_name for c in candidates[:1]]
            else:
                repos_to_check = [r.service_name for r in self._router._catalog.repos]

        zoekt_repos = None
        if self._zoekt is not None:
            try:
                zoekt_repos = await self._zoekt.list_indexed_repos()
            except Exception:
                zoekt_repos = set()
        if zoekt_repos is None:
            zoekt_repos = set()

        items = []
        for sn in repos_to_check or (["(all)"] if not repos_to_check else []):
            qdrant_count = None
            qdrant_status = "未知"
            if self._qstore is not None and sn != "(all)":
                try:
                    qdrant_count = await asyncio.wait_for(
                        asyncio.to_thread(self._qstore.count_points_by_service, service_name=sn),
                        timeout=15.0,
                    )
                    qdrant_status = "已索引" if (qdrant_count or 0) > 0 else "未索引"
                except Exception:
                    qdrant_status = "未知"

            zoekt_status = "已索引" if sn in zoekt_repos or sn == "(all)" else "未索引"
            if sn == "(all)":
                zoekt_status = f"已索引仓库数: {len(zoekt_repos)}"

            items.append({
                "service_name": sn,
                "qdrant_status": qdrant_status,
                "qdrant_count": qdrant_count,
                "zoekt_status": zoekt_status,
            })

        if not items and zoekt_repos:
            items.append({
                "service_name": "(zoekt_only)",
                "qdrant_status": "未配置",
                "zoekt_indexed_repos": list(zoekt_repos)[:50],
            })

        return ToolResult.text(json.dumps({"repos": items}, ensure_ascii=False))
