"""代码勘探类 MCP 工具：code.search、code.read。"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict

from root_seeker.domain import CandidateRepo, ZoektHit
from root_seeker.mcp.protocol import ToolResult, ToolSchema
from root_seeker.mcp.tools.base import BaseTool
from root_seeker.services.router import ServiceRouter


class CodeSearchTool(BaseTool):
    """code.search：基于 Zoekt 索引进行正则/关键词搜索。"""

    def __init__(self, zoekt_client):
        self._zoekt = zoekt_client

    @property
    def name(self) -> str:
        return "code.search"

    @property
    def schema(self) -> ToolSchema:
        return ToolSchema(
            name=self.name,
            description="基于 Zoekt 索引进行正则或关键词搜索，返回匹配的文件路径、行号、代码片段摘要。",
            inputSchema={
                "type": "object",
                "properties": {
                    "query": {"type": "string", "description": "正则或关键词"},
                    "repo_id": {"type": "string", "description": "可选，仓库/服务名，用于限定搜索范围"},
                    "file_pattern": {"type": "string", "description": "可选，文件模式如 *.py, *.java"},
                },
                "required": ["query"],
            },
        )

    async def run(self, args: Dict[str, Any], context: Dict[str, Any] | None = None) -> ToolResult:
        query = args.get("query")
        if not query or not isinstance(query, str):
            return ToolResult.error("缺少必填参数 query")
        repo_id = args.get("repo_id")
        file_pattern = args.get("file_pattern")

        repo_part = f"repo:{repo_id} " if repo_id else ""
        if file_pattern:
            query_str = f"{repo_part}file:{file_pattern} {query}".strip()
        else:
            query_str = f"{repo_part}{query}".strip() if repo_part else query

        try:
            hits: list[ZoektHit] = await self._zoekt.search(query=query_str, max_matches=30)
            out = []
            for h in hits[:20]:
                item = {
                    "file_path": h.file_path,
                    "line_number": h.line_number,
                    "preview": h.preview,
                    "repo": h.repo,
                }
                out.append(item)
            return ToolResult.text(json.dumps({"hits": out, "total": len(hits)}, ensure_ascii=False))
        except Exception as e:
            return ToolResult.error(f"code.search 执行失败: {str(e)}")


class CodeReadTool(BaseTool):
    """code.read：基于 EvidenceBuilder 逻辑安全读取文件内容（含路径校验）。"""

    def __init__(self, router: ServiceRouter):
        self._router = router

    @property
    def name(self) -> str:
        return "code.read"

    @property
    def schema(self) -> ToolSchema:
        return ToolSchema(
            name=self.name,
            description="读取指定仓库、文件路径的代码内容，支持按行范围截取。",
            inputSchema={
                "type": "object",
                "properties": {
                    "repo_id": {"type": "string", "description": "服务名/仓库标识"},
                    "file_path": {"type": "string", "description": "相对仓库根目录的文件路径"},
                    "start_line": {"type": "integer", "description": "可选，起始行号"},
                    "end_line": {"type": "integer", "description": "可选，结束行号"},
                },
                "required": ["repo_id", "file_path"],
            },
        )

    async def run(self, args: Dict[str, Any], context: Dict[str, Any] | None = None) -> ToolResult:
        repo_id = args.get("repo_id")
        file_path = args.get("file_path")
        start_line = args.get("start_line")
        end_line = args.get("end_line")

        if not repo_id or not file_path:
            return ToolResult.error("缺少必填参数 repo_id 或 file_path")

        candidates: list[CandidateRepo] = self._router.route(str(repo_id))
        if not candidates:
            return ToolResult.error(f"未找到 repo_id={repo_id} 对应的仓库配置")
        repo = candidates[0]
        repo_local_dir = repo.local_dir

        path = Path(repo_local_dir) / file_path.lstrip("/")
        try:
            full_path = path.resolve()
            repo_path = Path(repo_local_dir).resolve()
            if not str(full_path).startswith(str(repo_path)):
                return ToolResult.error("检测到路径遍历，已拒绝")
        except (ValueError, OSError):
            return ToolResult.error(f"无效的文件路径: {file_path}")

        if not path.exists() or not path.is_file():
            return ToolResult.error(f"文件不存在: {file_path}")

        try:
            lines = path.read_text(encoding="utf-8", errors="replace").splitlines()
        except Exception as e:
            return ToolResult.error(f"读取文件失败: {str(e)}")

        if start_line is not None or end_line is not None:
            s = max(1, int(start_line) if start_line is not None else 1)
            e = min(len(lines), int(end_line) if end_line is not None else len(lines))
            snippet_lines = lines[s - 1 : e]
        else:
            snippet_lines = lines[:500]
            s, e = 1, len(snippet_lines)

        content = "\n".join(snippet_lines)
        numbered = "\n".join(f"{i + s:4d} | {line}" for i, line in enumerate(snippet_lines))
        return ToolResult.text(
            json.dumps(
                {"file_path": file_path, "start_line": s, "end_line": e, "content": numbered},
                ensure_ascii=False,
            )
        )
