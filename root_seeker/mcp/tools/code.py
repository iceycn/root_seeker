"""代码勘探类 MCP 工具：code.search、code.read。"""

from __future__ import annotations

import json
import re
import zipfile
from pathlib import Path
from typing import Any, Dict


def _zoekt_safe_file_pattern(pattern: str) -> str:
    """将 glob 风格 file_pattern 转为 Zoekt 可接受的正则，避免 * 等导致 400。"""
    if not pattern or not isinstance(pattern, str):
        return ".*"
    s = pattern.strip()
    # * -> .*  ? -> .  . -> \.  (其他正则特殊字符也转义)
    s = re.escape(s).replace(r"\*", ".*").replace(r"\?", ".")
    return s if s else ".*"

from root_seeker.domain import CandidateRepo, ZoektHit
from root_seeker.mcp.protocol import ToolResult, ToolSchema
from root_seeker.mcp.tools.base import BaseTool
from root_seeker.services.router import ServiceRouter

def _get_dep_cache_roots() -> list[Path]:
    from root_seeker.services.dep_cache_config import get_dep_cache_roots
    return get_dep_cache_roots()


def _is_under_cache(path: Path) -> bool:
    """路径是否在依赖缓存白名单内。"""
    try:
        resolved = path.resolve()
        for root in _get_dep_cache_roots():
            if str(resolved).startswith(str(root.resolve())):
                return True
    except (OSError, ValueError):
        pass
    return False


def _read_from_jar(jar_path: Path, inner_path: str, start_line: int | None, end_line: int | None) -> tuple[str, int, int]:
    """从 jar 内读取文件内容。返回 (content, start, end)。"""
    inner_path = inner_path.lstrip("/").replace("\\", "/")
    with zipfile.ZipFile(jar_path, "r") as zf:
        try:
            data = zf.read(inner_path)
        except KeyError:
            raise FileNotFoundError(f"jar 内不存在: {inner_path}")
    text = data.decode("utf-8", errors="replace")
    lines = text.splitlines()
    s = max(1, start_line or 1)
    e = min(len(lines), end_line or len(lines))
    snippet = lines[s - 1 : e]
    content = "\n".join(snippet)
    numbered = "\n".join(f"{i + s:4d} | {line}" for i, line in enumerate(snippet))
    return numbered, s, e


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
            # Zoekt file: 使用正则，*.java 中 * 会报错，需转为 .*\.java
            safe_pattern = _zoekt_safe_file_pattern(file_pattern)
            query_str = f"{repo_part}file:{safe_pattern} {query}".strip()
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
            description="读取指定仓库、文件路径的代码内容。repo_id=dep_cache 时可读取依赖缓存（~/.m2、~/.gradle）内 sources.jar，file_path 格式：path/to/sources.jar!/path/inside。",
            inputSchema={
                "type": "object",
                "properties": {
                    "repo_id": {"type": "string", "description": "服务名/仓库标识，或 dep_cache 表示依赖缓存"},
                    "file_path": {"type": "string", "description": "相对仓库根目录的文件路径；dep_cache 时为 jar!/inner 或相对 m2 的路径"},
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

        # 依赖缓存白名单：repo_id=dep_cache 时从 ~/.m2、~/.gradle 读取
        if str(repo_id).lower() in ("dep_cache", "__dep_cache__"):
            if "!" in file_path:
                jar_part, inner_part = file_path.split("!", 1)
                jar_part_clean = jar_part.replace("file://", "").strip("/")
                jar_path = Path(jar_part_clean)
                if not jar_path.exists():
                    for root in _get_dep_cache_roots():
                        candidate = root / jar_part_clean.lstrip("/")
                        if candidate.exists():
                            jar_path = candidate
                            break
                if not jar_path.exists() or not jar_path.is_file():
                    return ToolResult.error(f"依赖缓存中未找到: {file_path}")
                if not _is_under_cache(jar_path):
                    return ToolResult.error("路径不在依赖缓存白名单内")
                try:
                    numbered, s, e = _read_from_jar(jar_path, inner_part, start_line, end_line)
                except FileNotFoundError as err:
                    return ToolResult.error(str(err))
                return ToolResult.text(
                    json.dumps(
                        {"file_path": file_path, "start_line": s, "end_line": e, "content": numbered, "source": "dep_cache"},
                        ensure_ascii=False,
                    )
                )
            # 相对 m2 路径
            for root in _get_dep_cache_roots():
                path = root / file_path.lstrip("/")
                if path.exists() and path.is_file():
                    if not _is_under_cache(path):
                        continue
                    try:
                        lines = path.read_text(encoding="utf-8", errors="replace").splitlines()
                    except Exception as e:
                        return ToolResult.error(f"读取失败: {e}")
                    s = max(1, int(start_line) if start_line is not None else 1)
                    e = min(len(lines), int(end_line) if end_line is not None else len(lines))
                    snippet = lines[s - 1 : e]
                    numbered = "\n".join(f"{i + s:4d} | {line}" for i, line in enumerate(snippet))
                    return ToolResult.text(
                        json.dumps(
                            {"file_path": file_path, "start_line": s, "end_line": e, "content": numbered, "source": "dep_cache"},
                            ensure_ascii=False,
                        )
                    )
            return ToolResult.error(f"依赖缓存中未找到: {file_path}")

        candidates: list[CandidateRepo] = self._router.route(str(repo_id))
        if not candidates:
            return ToolResult.error(f"未找到 repo_id={repo_id} 对应的仓库配置")
        repo = candidates[0]
        repo_local_dir = repo.local_dir

        fp_clean = file_path.replace("\\", "/").lstrip("/")
        path = Path(repo_local_dir) / fp_clean
        # Java/Kotlin 包路径兜底：AI 可能传 com/xxx/Foo.java，实际在 src/main/java/com/xxx/Foo.java
        if (not path.exists() or not path.is_file()) and (
            fp_clean.endswith(".java") or fp_clean.endswith(".kt")
        ):
            for prefix in ("src/main/java", "src/main/kotlin", "src"):
                candidate = Path(repo_local_dir) / prefix / fp_clean
                if candidate.exists() and candidate.is_file():
                    path = candidate
                    break
            # 仍未找到时，按文件名在 src 下搜索（避免全仓扫描）
            if not path.exists() or not path.is_file():
                base = Path(repo_local_dir)
                found_path: Path | None = None
                for src_dir in (base / "src", base / "src/main"):
                    if not src_dir.is_dir():
                        continue
                    for found in src_dir.rglob(Path(fp_clean).name):
                        if found.is_file():
                            found_path = found
                            break
                    if found_path is not None:
                        path = found_path
                        break

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


class CodeResolveSymbolTool(BaseTool):
    """code.resolve_symbol：当 LSP 不可用或返回不可读 URI 时，基于已物化源码与仓库做符号兜底定位。"""

    def __init__(self, zoekt_client, router: ServiceRouter):
        self._zoekt = zoekt_client
        self._router = router

    @property
    def name(self) -> str:
        return "code.resolve_symbol"

    @property
    def schema(self) -> ToolSchema:
        return ToolSchema(
            name=self.name,
            description="当 LSP 返回 jdt:///zip:// 等不可读 URI 时，基于 Zoekt 在仓库中搜索，并可选在已物化依赖源码（sources.jar）中搜索。",
            inputSchema={
                "type": "object",
                "properties": {
                    "symbol": {"type": "string", "description": "符号名（类名、方法名等）"},
                    "repo_id": {"type": "string", "description": "可选，限定搜索范围，有值时同时搜索该仓库的依赖 sources"},
                },
                "required": ["symbol"],
            },
        )

    async def run(self, args: Dict[str, Any], context: Dict[str, Any] | None = None) -> ToolResult:
        symbol = args.get("symbol")
        if not symbol or not isinstance(symbol, str):
            return ToolResult.error("缺少必填参数 symbol")
        repo_id = args.get("repo_id") or (context or {}).get("service_name")
        out: list[dict] = []

        # 1. Zoekt 仓库内搜索
        try:
            repo_part = f"repo:{repo_id} " if repo_id else ""
            query_str = f"{repo_part}{symbol}".strip()
            hits: list[ZoektHit] = await self._zoekt.search(query=query_str, max_matches=20)
            for h in hits[:15]:
                out.append({
                    "file_path": h.file_path,
                    "line_number": h.line_number,
                    "preview": h.preview,
                    "location": {"file_path": h.file_path, "range": {"start": {"line": h.line_number or 0, "character": 0}}},
                    "source": "zoekt",
                })
        except Exception as e:
            pass  # Zoekt 失败时继续尝试依赖源码

        # 2. 依赖源码搜索：当有 repo_id 时；非 Java/Python 仅靠 Zoekt（符号索引+约束检索兜底）
        if repo_id and len(out) < 15:
            candidates = self._router.route(str(repo_id))
            if candidates:
                project_root = candidates[0].local_dir
                from root_seeker.services.dependency_sources import (
                    fetch_java_sources,
                    fetch_python_package_paths,
                    materialize_maven_sources,
                    resolve_symbol_in_python_sources,
                    resolve_symbol_in_sources,
                    resolve_symbol_generic_fallback,
                )
                from root_seeker.services.external_deps import parse_external
                deps = parse_external(project_root)
                limit_left = 15 - len(out)
                if deps.ecosystem in ("maven", "gradle"):
                    coords = fetch_java_sources(project_root)
                    roots = materialize_maven_sources(coords)
                    dep_locs = resolve_symbol_in_sources(symbol, roots, limit=limit_left)
                elif deps.ecosystem == "python":
                    pkg_paths = fetch_python_package_paths(project_root)
                    dep_locs = resolve_symbol_in_python_sources(symbol, pkg_paths, limit=limit_left)
                else:
                    # 非 AST 强语言兜底：Go/JS 等用正则约束检索 + 片段验证
                    dep_locs = resolve_symbol_generic_fallback(project_root, symbol, limit=limit_left)
                for loc in dep_locs:
                    out.append({
                        "file_path": loc.file_path,
                        "line_number": loc.line,
                        "preview": loc.preview or "",
                        "location": {"file_path": loc.file_path, "range": {"start": {"line": loc.line, "character": loc.character}}},
                        "source": "dep_sources",
                    })

        return ToolResult.text(json.dumps({"locations": out, "total": len(out)}, ensure_ascii=False))
