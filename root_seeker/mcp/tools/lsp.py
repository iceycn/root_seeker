"""Headless LSP MCP 工具：lsp.start、lsp.stop、lsp.workspace_symbol、lsp.definition、lsp.references、lsp.hover、lsp.document_symbols。"""

from __future__ import annotations

import json
from typing import Any, Dict

from root_seeker.mcp.protocol import ErrorCode, ToolResult, ToolSchema
from root_seeker.mcp.tools.base import BaseTool
from root_seeker.services.lsp_manager import (
    CodeLocation,
    HoverInfo,
    LSPSessionManager,
    SymbolLocation,
)
from root_seeker.services.router import ServiceRouter

# 全局 LSP 会话管理器（单例）
_lsp_manager: LSPSessionManager | None = None


def get_lsp_manager() -> LSPSessionManager:
    global _lsp_manager
    if _lsp_manager is None:
        _lsp_manager = LSPSessionManager()
    return _lsp_manager


def _as_dict(obj: Any) -> Any:
    from dataclasses import asdict, is_dataclass
    if is_dataclass(obj) and not isinstance(obj, type):
        return asdict(obj)
    if isinstance(obj, list):
        return [_as_dict(x) for x in obj]
    return obj


def _lsp_error_with_degraded(msg: str, error_code: str) -> ToolResult:
    """LSP 工具错误返回，附带 degraded_modes 供下一轮决策回退。"""
    payload = {"error": msg, "degraded_modes": ["lsp_unavailable"]}
    return ToolResult.error(json.dumps(payload, ensure_ascii=False), error_code=error_code)


class LspStartTool(BaseTool):
    """lsp.start：启动 Headless LSP 会话（Java/Python）。"""

    def __init__(self, router: ServiceRouter):
        self._router = router

    @property
    def name(self) -> str:
        return "lsp.start"

    @property
    def schema(self) -> ToolSchema:
        return ToolSchema(
            name=self.name,
            description="启动对应语言的 LSP 会话（stdio），完成 initialize。同一 project_root+language 幂等复用。Python 默认使用 pylsp；Java 需 extra 配置 jdtls_launcher_path 等。",
            inputSchema={
                "type": "object",
                "properties": {
                    "language": {"type": "string", "enum": ["java", "python"]},
                    "project_root": {"type": "string"},
                    "repo_id": {"type": "string"},
                    "workspace_name": {"type": "string"},
                    "extra": {"type": "object", "description": "Java: jdtls_launcher_path, jdtls_config_dir, workspace_data_dir; Python: python_path, venv_dir, lsp_command(支持 Pyright: [\"pyright-langserver\", \"--stdio\"])"},
                },
                "required": ["language"],
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
            return ToolResult.error("缺少 project_root 或 repo_id", error_code=ErrorCode.INVALID_PARAMS)
        language = args.get("language")
        if language not in ("java", "python"):
            return ToolResult.error("language 必须为 java 或 python", error_code=ErrorCode.INVALID_PARAMS)
        try:
            ok, msg = await get_lsp_manager().start(
                language=language,
                project_root=project_root,
                workspace_name=args.get("workspace_name"),
                extra=args.get("extra"),
            )
            if not ok:
                return _lsp_error_with_degraded(msg, ErrorCode.DEPENDENCY_UNAVAILABLE)
            return ToolResult.text(json.dumps({"ok": True, "message": msg}, ensure_ascii=False))
        except Exception as e:
            err_code = ErrorCode.TOOL_TIMEOUT if "超时" in str(e) else ErrorCode.INTERNAL_ERROR
            return _lsp_error_with_degraded(f"lsp.start 失败: {e}", err_code)


class LspStopTool(BaseTool):
    """lsp.stop：关闭 LSP 会话。"""

    def __init__(self, router: ServiceRouter):
        self._router = router

    @property
    def name(self) -> str:
        return "lsp.stop"

    @property
    def schema(self) -> ToolSchema:
        return ToolSchema(
            name=self.name,
            description="关闭指定 language+project_root 的 LSP 会话并清理子进程。",
            inputSchema={
                "type": "object",
                "properties": {
                    "language": {"type": "string", "enum": ["java", "python"]},
                    "project_root": {"type": "string"},
                    "repo_id": {"type": "string"},
                },
                "required": ["language"],
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
            return ToolResult.error("缺少 project_root 或 repo_id", error_code=ErrorCode.INVALID_PARAMS)
        await get_lsp_manager().stop(args.get("language", ""), project_root)
        return ToolResult.text(json.dumps({"ok": True, "message": "已关闭"}, ensure_ascii=False))


def _lsp_tool_resolve_project_root(tool: BaseTool, args: Dict[str, Any], context: Dict[str, Any] | None, router: ServiceRouter) -> str | None:
    if args.get("project_root"):
        return args["project_root"]
    repo_id = args.get("repo_id") or (context or {}).get("service_name")
    if repo_id:
        candidates = router.route(str(repo_id))
        if candidates:
            return candidates[0].local_dir
    return None


class LspWorkspaceSymbolTool(BaseTool):
    """lsp.workspace_symbol：工作区符号搜索。"""

    def __init__(self, router: ServiceRouter):
        self._router = router

    @property
    def name(self) -> str:
        return "lsp.workspace_symbol"

    @property
    def schema(self) -> ToolSchema:
        return ToolSchema(
            name=self.name,
            description="在工作区中搜索符号（类、方法、函数等）。需先 lsp.start。注意：pylsp 不支持 workspace/symbol，Python 需 Pyright 等；pylsp 支持 document_symbols。",
            inputSchema={
                "type": "object",
                "properties": {
                    "language": {"type": "string", "enum": ["java", "python"]},
                    "project_root": {"type": "string"},
                    "repo_id": {"type": "string"},
                    "query": {"type": "string"},
                    "limit": {"type": "integer"},
                },
                "required": ["language", "query"],
            },
        )

    async def run(self, args: Dict[str, Any], context: Dict[str, Any] | None = None) -> ToolResult:
        project_root = _lsp_tool_resolve_project_root(self, args, context, self._router)
        if not project_root:
            return ToolResult.error("缺少 project_root 或 repo_id", error_code=ErrorCode.INVALID_PARAMS)
        try:
            symbols = await get_lsp_manager().workspace_symbol(
                args["language"], project_root,
                args.get("query", ""),
                limit=int(args.get("limit") or 20),
            )
            out = [_as_dict(s) for s in symbols]
            return ToolResult.text(json.dumps(out, ensure_ascii=False))
        except TimeoutError:
            return _lsp_error_with_degraded("LSP 请求超时", ErrorCode.TOOL_TIMEOUT)
        except RuntimeError as e:
            return _lsp_error_with_degraded(str(e), ErrorCode.DEPENDENCY_UNAVAILABLE)
        except Exception as e:
            return _lsp_error_with_degraded(f"lsp.workspace_symbol 失败: {e}", ErrorCode.INTERNAL_ERROR)


class LspDefinitionTool(BaseTool):
    """lsp.definition：跳转到定义。"""

    def __init__(self, router: ServiceRouter):
        self._router = router

    @property
    def name(self) -> str:
        return "lsp.definition"

    @property
    def schema(self) -> ToolSchema:
        return ToolSchema(
            name=self.name,
            description="获取符号定义位置。line/character 为 0-based。需先 lsp.start。",
            inputSchema={
                "type": "object",
                "properties": {
                    "language": {"type": "string", "enum": ["java", "python"]},
                    "project_root": {"type": "string"},
                    "repo_id": {"type": "string"},
                    "file_path": {"type": "string"},
                    "line": {"type": "integer"},
                    "character": {"type": "integer"},
                },
                "required": ["language", "file_path", "line", "character"],
            },
        )

    async def run(self, args: Dict[str, Any], context: Dict[str, Any] | None = None) -> ToolResult:
        project_root = _lsp_tool_resolve_project_root(self, args, context, self._router)
        if not project_root:
            return ToolResult.error("缺少 project_root 或 repo_id", error_code=ErrorCode.INVALID_PARAMS)
        try:
            locs = await get_lsp_manager().definition(
                args["language"], project_root,
                args["file_path"],
                int(args.get("line", 0)),
                int(args.get("character", 0)),
            )
            out = [{"location": {"file_path": l.file_path, "range": l.range}, "preview": l.preview} for l in locs]
            return ToolResult.text(json.dumps(out, ensure_ascii=False))
        except TimeoutError:
            return _lsp_error_with_degraded("LSP 请求超时", ErrorCode.TOOL_TIMEOUT)
        except RuntimeError as e:
            return _lsp_error_with_degraded(str(e), ErrorCode.DEPENDENCY_UNAVAILABLE)
        except Exception as e:
            return _lsp_error_with_degraded(f"lsp.definition 失败: {e}", ErrorCode.INTERNAL_ERROR)


class LspReferencesTool(BaseTool):
    """lsp.references：查找引用。"""

    def __init__(self, router: ServiceRouter):
        self._router = router

    @property
    def name(self) -> str:
        return "lsp.references"

    @property
    def schema(self) -> ToolSchema:
        return ToolSchema(
            name=self.name,
            description="查找符号的引用位置。line/character 为 0-based。需先 lsp.start。",
            inputSchema={
                "type": "object",
                "properties": {
                    "language": {"type": "string", "enum": ["java", "python"]},
                    "project_root": {"type": "string"},
                    "repo_id": {"type": "string"},
                    "file_path": {"type": "string"},
                    "line": {"type": "integer"},
                    "character": {"type": "integer"},
                    "includeDeclaration": {"type": "boolean"},
                    "limit": {"type": "integer"},
                },
                "required": ["language", "file_path", "line", "character"],
            },
        )

    async def run(self, args: Dict[str, Any], context: Dict[str, Any] | None = None) -> ToolResult:
        project_root = _lsp_tool_resolve_project_root(self, args, context, self._router)
        if not project_root:
            return ToolResult.error("缺少 project_root 或 repo_id", error_code=ErrorCode.INVALID_PARAMS)
        try:
            locs = await get_lsp_manager().references(
                args["language"], project_root,
                args["file_path"],
                int(args.get("line", 0)),
                int(args.get("character", 0)),
                include_declaration=bool(args.get("includeDeclaration", False)),
                limit=int(args.get("limit") or 50),
            )
            out = [{"location": {"file_path": l.file_path, "range": l.range}, "preview": l.preview} for l in locs]
            return ToolResult.text(json.dumps(out, ensure_ascii=False))
        except TimeoutError:
            return _lsp_error_with_degraded("LSP 请求超时", ErrorCode.TOOL_TIMEOUT)
        except RuntimeError as e:
            return _lsp_error_with_degraded(str(e), ErrorCode.DEPENDENCY_UNAVAILABLE)
        except Exception as e:
            return _lsp_error_with_degraded(f"lsp.references 失败: {e}", ErrorCode.INTERNAL_ERROR)


class LspHoverTool(BaseTool):
    """lsp.hover：悬停信息。"""

    def __init__(self, router: ServiceRouter):
        self._router = router

    @property
    def name(self) -> str:
        return "lsp.hover"

    @property
    def schema(self) -> ToolSchema:
        return ToolSchema(
            name=self.name,
            description="获取符号的悬停文档（类型、文档等）。line/character 为 0-based。需先 lsp.start。",
            inputSchema={
                "type": "object",
                "properties": {
                    "language": {"type": "string", "enum": ["java", "python"]},
                    "project_root": {"type": "string"},
                    "repo_id": {"type": "string"},
                    "file_path": {"type": "string"},
                    "line": {"type": "integer"},
                    "character": {"type": "integer"},
                },
                "required": ["language", "file_path", "line", "character"],
            },
        )

    async def run(self, args: Dict[str, Any], context: Dict[str, Any] | None = None) -> ToolResult:
        project_root = _lsp_tool_resolve_project_root(self, args, context, self._router)
        if not project_root:
            return ToolResult.error("缺少 project_root 或 repo_id", error_code=ErrorCode.INVALID_PARAMS)
        try:
            info = await get_lsp_manager().hover(
                args["language"], project_root,
                args["file_path"],
                int(args.get("line", 0)),
                int(args.get("character", 0)),
            )
            if not info:
                return ToolResult.text(json.dumps({"markdown": "", "range": None}, ensure_ascii=False))
            return ToolResult.text(json.dumps(_as_dict(info), ensure_ascii=False))
        except TimeoutError:
            return _lsp_error_with_degraded("LSP 请求超时", ErrorCode.TOOL_TIMEOUT)
        except RuntimeError as e:
            return _lsp_error_with_degraded(str(e), ErrorCode.DEPENDENCY_UNAVAILABLE)
        except Exception as e:
            return _lsp_error_with_degraded(f"lsp.hover 失败: {e}", ErrorCode.INTERNAL_ERROR)


class LspDocumentSymbolsTool(BaseTool):
    """lsp.document_symbols：文档符号树。"""

    def __init__(self, router: ServiceRouter):
        self._router = router

    @property
    def name(self) -> str:
        return "lsp.document_symbols"

    @property
    def schema(self) -> ToolSchema:
        return ToolSchema(
            name=self.name,
            description="获取文件的符号树（类、方法、函数等）。需先 lsp.start。",
            inputSchema={
                "type": "object",
                "properties": {
                    "language": {"type": "string", "enum": ["java", "python"]},
                    "project_root": {"type": "string"},
                    "repo_id": {"type": "string"},
                    "file_path": {"type": "string"},
                },
                "required": ["language", "file_path"],
            },
        )

    async def run(self, args: Dict[str, Any], context: Dict[str, Any] | None = None) -> ToolResult:
        project_root = _lsp_tool_resolve_project_root(self, args, context, self._router)
        if not project_root:
            return ToolResult.error("缺少 project_root 或 repo_id", error_code=ErrorCode.INVALID_PARAMS)
        try:
            symbols = await get_lsp_manager().document_symbols(
                args["language"], project_root, args["file_path"]
            )
            return ToolResult.text(json.dumps(symbols, ensure_ascii=False))
        except TimeoutError:
            return _lsp_error_with_degraded("LSP 请求超时", ErrorCode.TOOL_TIMEOUT)
        except RuntimeError as e:
            return _lsp_error_with_degraded(str(e), ErrorCode.DEPENDENCY_UNAVAILABLE)
        except Exception as e:
            return _lsp_error_with_degraded(f"lsp.document_symbols 失败: {e}", ErrorCode.INTERNAL_ERROR)
