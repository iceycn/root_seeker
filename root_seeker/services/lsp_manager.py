"""Headless LSP 服务层：管理语言服务器会话，提供 workspace_symbol/definition/references/hover/document_symbols。"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import shutil
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

DEFAULT_INIT_TIMEOUT = 60.0
DEFAULT_REQUEST_TIMEOUT = 15.0


@dataclass
class SymbolLocation:
    name: str
    kind: str
    containerName: str | None
    location: dict  # {file_path, range}


@dataclass
class CodeLocation:
    file_path: str
    range: dict
    preview: str | None = None


@dataclass
class HoverInfo:
    markdown: str
    range: dict | None = None


def _get_dep_cache_roots() -> list[Path]:
    from root_seeker.services.dep_cache_config import get_dep_cache_roots
    return get_dep_cache_roots()


def _try_resolve_jdt_uri(uri: str) -> str | None:
    """尝试将 jdt://contents/groupId/artifactId/version/... 映射到 ~/.m2 中的 sources.jar。"""
    if not uri.startswith("jdt://contents/"):
        return None
    rest = uri[14:].strip("/")
    parts = rest.split("/")
    if len(parts) < 3:
        return None
    group_id, artifact_id, version = parts[0], parts[1], parts[2]
    group_path = group_id.replace(".", "/")
    for root in _get_dep_cache_roots():
        base = root / group_path / artifact_id / version
        if not base.exists():
            continue
        for f in base.glob("*-sources.jar"):
            inner = "/".join(parts[3:]) if len(parts) > 3 else ""
            return f"{f.as_uri()}!/{inner}" if inner else str(f)
    return None


def _try_resolve_zip_uri(uri: str) -> str | None:
    """尝试解析 zip:///path/to.jar!/inner/path 格式。"""
    if not uri.startswith("zip://"):
        return None
    # zip:///abs/path/to.jar!/path/inside
    rest = uri[6:].lstrip("/")
    if "!" in rest:
        jar_path, inner = rest.split("!", 1)
        full = Path(jar_path)
        if full.exists():
            return f"{full.as_uri()}!{inner}"
    return None


def _uri_to_file_path(uri: str, project_root: str) -> str:
    """将 LSP URI 转为 file_path。file:// 转相对路径；jdt:// zip:// 尝试映射到依赖缓存。"""
    if uri.startswith("file://"):
        path = uri[7:]
        if path.startswith("/"):
            try:
                rel = Path(path).relative_to(Path(project_root).resolve())
                return str(rel).replace("\\", "/")
            except ValueError:
                return path
        return path
    if uri.startswith("jdt://"):
        resolved = _try_resolve_jdt_uri(uri)
        if resolved:
            return resolved
    if uri.startswith("zip://"):
        resolved = _try_resolve_zip_uri(uri)
        if resolved:
            return resolved
    return uri


def _file_path_to_uri(file_path: str, project_root: str) -> str:
    """将 file_path 转为 LSP URI。"""
    if file_path.startswith("file://"):
        return file_path
    full = (Path(project_root) / file_path.lstrip("/")).resolve()
    uri = full.as_uri()
    return uri if uri.startswith("file:") else f"file://{full}"


class LSPClient:
    """LSP 客户端：JSON-RPC 2.0 over stdio，Content-Length framing。"""

    def __init__(
        self,
        project_root: str,
        language: str,
        process: asyncio.subprocess.Process,
        timeout: float = DEFAULT_REQUEST_TIMEOUT,
    ):
        self.project_root = project_root
        self.language = language
        self._process = process
        self._timeout = timeout
        self._request_id = 0
        self._initialized = False
        self._open_docs: dict[str, int] = {}  # uri -> version

    def _next_id(self) -> int:
        self._request_id += 1
        return self._request_id

    def _encode_message(self, obj: dict) -> bytes:
        body = json.dumps(obj, ensure_ascii=False).encode("utf-8")
        return f"Content-Length: {len(body)}\r\n\r\n".encode("ascii") + body

    async def _read_message(self) -> dict | None:
        """读取一条 LSP 消息（Content-Length framing）。"""
        header = b""
        while b"\r\n\r\n" not in header:
            chunk = await self._process.stdout.read(1)
            if not chunk:
                return None
            header += chunk
        lines = header.decode("ascii").split("\r\n")
        length = 0
        for line in lines:
            if line.lower().startswith("content-length:"):
                length = int(line.split(":", 1)[1].strip())
                break
        if length <= 0:
            return None
        body = await self._process.stdout.readexactly(length)
        return json.loads(body.decode("utf-8"))

    async def _send(self, obj: dict) -> None:
        self._process.stdin.write(self._encode_message(obj))
        await self._process.stdin.drain()

    async def _request(self, method: str, params: dict | None = None) -> Any:
        """发送请求并等待响应。"""
        req_id = self._next_id()
        msg = {"jsonrpc": "2.0", "id": req_id, "method": method}
        if params is not None:
            msg["params"] = params
        await self._send(msg)
        deadline = time.monotonic() + self._timeout
        while time.monotonic() < deadline:
            resp = await asyncio.wait_for(self._read_message(), timeout=5.0)
            if resp is None:
                raise TimeoutError("LSP 无响应")
            if "id" in resp and resp["id"] == req_id:
                if "error" in resp:
                    raise RuntimeError(resp["error"].get("message", "LSP error"))
                return resp.get("result")
            if "method" in resp and resp.get("method") == "window/logMessage":
                continue
        raise TimeoutError(f"LSP 请求 {method} 超时")

    async def initialize(self) -> None:
        """发送 initialize 并 initialized。"""
        root_uri = _file_path_to_uri(".", self.project_root)
        result = await self._request(
            "initialize",
            {
                "processId": os.getpid(),
                "rootUri": root_uri,
                "workspaceFolders": [{"uri": root_uri, "name": Path(self.project_root).name}],
                "capabilities": {},
            },
        )
        await self._send({"jsonrpc": "2.0", "method": "initialized", "params": {}})
        self._initialized = True
        logger.debug("[LSP] 已初始化 language=%s root=%s", self.language, self.project_root)

    async def ensure_document_open(self, file_path: str) -> None:
        """确保文档已打开（部分 server 需要 didOpen 才能提供语义）。"""
        uri = _file_path_to_uri(file_path, self.project_root)
        if uri in self._open_docs:
            return
        path = Path(self.project_root) / file_path.lstrip("/")
        if not path.exists():
            return
        try:
            content = path.read_text(encoding="utf-8", errors="replace")
        except Exception:
            return
        version = self._open_docs.get(uri, 0) + 1
        self._open_docs[uri] = version
        await self._send(
            {
                "jsonrpc": "2.0",
                "method": "textDocument/didOpen",
                "params": {
                    "textDocument": {
                        "uri": uri,
                        "languageId": self.language,
                        "version": version,
                        "text": content,
                    },
                },
            }
        )

    async def workspace_symbol(self, query: str, limit: int = 20) -> list[SymbolLocation]:
        """workspace/symbol 请求。"""
        result = await self._request("workspace/symbol", {"query": query})
        if not result:
            return []
        out: list[SymbolLocation] = []
        for item in result[:limit]:
            loc = item.get("location", {})
            uri = loc.get("uri", "")
            if isinstance(loc.get("range"), dict):
                rng = loc["range"]
            else:
                rng = {}
            out.append(
                SymbolLocation(
                    name=item.get("name", ""),
                    kind=str(item.get("kind", "")),
                    containerName=item.get("containerName"),
                    location={"file_path": _uri_to_file_path(uri, self.project_root), "range": rng},
                )
            )
        return out

    async def definition(self, file_path: str, line: int, character: int) -> list[CodeLocation]:
        """textDocument/definition 请求。"""
        await self.ensure_document_open(file_path)
        uri = _file_path_to_uri(file_path, self.project_root)
        result = await self._request(
            "textDocument/definition",
            {"textDocument": {"uri": uri}, "position": {"line": line, "character": character}},
        )
        if result is None:
            return []
        if isinstance(result, dict):
            result = [result]
        out: list[CodeLocation] = []
        for loc in result:
            uri = loc.get("uri", "")
            rng = loc.get("range", {})
            out.append(
                CodeLocation(
                    file_path=_uri_to_file_path(uri, self.project_root),
                    range=rng,
                    preview=None,
                )
            )
        return out

    async def references(
        self,
        file_path: str,
        line: int,
        character: int,
        include_declaration: bool = False,
        limit: int = 50,
    ) -> list[CodeLocation]:
        """textDocument/references 请求。"""
        await self.ensure_document_open(file_path)
        uri = _file_path_to_uri(file_path, self.project_root)
        result = await self._request(
            "textDocument/references",
            {
                "textDocument": {"uri": uri},
                "position": {"line": line, "character": character},
                "context": {"includeDeclaration": include_declaration},
            },
        )
        if not result:
            return []
        out: list[CodeLocation] = []
        for loc in result[:limit]:
            uri = loc.get("uri", "")
            rng = loc.get("range", {})
            out.append(
                CodeLocation(
                    file_path=_uri_to_file_path(uri, self.project_root),
                    range=rng,
                    preview=None,
                )
            )
        return out

    async def hover(self, file_path: str, line: int, character: int) -> HoverInfo | None:
        """textDocument/hover 请求。"""
        await self.ensure_document_open(file_path)
        uri = _file_path_to_uri(file_path, self.project_root)
        result = await self._request(
            "textDocument/hover",
            {"textDocument": {"uri": uri}, "position": {"line": line, "character": character}},
        )
        if not result:
            return None
        content = result.get("contents")
        if isinstance(content, dict) and "value" in content:
            markdown = content["value"]
        elif isinstance(content, list):
            markdown = "\n".join(
                c.get("value", c) if isinstance(c, dict) else str(c) for c in content
            )
        else:
            markdown = str(content) if content else ""
        return HoverInfo(markdown=markdown, range=result.get("range"))

    async def document_symbols(self, file_path: str) -> list[dict]:
        """textDocument/documentSymbol 请求。"""
        await self.ensure_document_open(file_path)
        uri = _file_path_to_uri(file_path, self.project_root)
        result = await self._request(
            "textDocument/documentSymbol",
            {"textDocument": {"uri": uri}},
        )
        if not result:
            return []
        out: list[dict] = []
        for item in result:
            rng = item.get("range", {})
            sel = item.get("selectionRange", rng)
            out.append(
                {
                    "name": item.get("name", ""),
                    "kind": item.get("kind", 0),
                    "range": rng,
                    "selectionRange": sel,
                    "children": item.get("children"),
                }
            )
        return out

    async def shutdown(self) -> None:
        """发送 shutdown 并退出。"""
        try:
            await self._request("shutdown")
            await self._send({"jsonrpc": "2.0", "method": "exit"})
        except Exception:
            pass
        try:
            self._process.terminate()
            await asyncio.wait_for(self._process.wait(), timeout=5.0)
        except Exception:
            try:
                self._process.kill()
            except Exception:
                pass


def _get_python_command(extra: dict | None) -> list[str]:
    """获取 Python LSP 启动命令。"""
    extra = extra or {}
    if extra.get("python_path"):
        python = extra["python_path"]
    elif extra.get("venv_dir"):
        venv = Path(extra["venv_dir"])
        if (venv / "bin" / "python").exists():
            python = str(venv / "bin" / "python")
        else:
            python = str(venv / "Scripts" / "python.exe") if (venv / "Scripts" / "python.exe").exists() else "python"
    else:
        python = shutil.which("python3") or shutil.which("python") or "python"
    cmd = extra.get("lsp_command") or [python, "-m", "pylsp"]
    return cmd if isinstance(cmd, list) else [cmd]


def _get_java_command(project_root: str, extra: dict | None) -> list[str]:
    """获取 Java JDT LS 启动命令。"""
    extra = extra or {}
    java_home = extra.get("java_home") or os.environ.get("JAVA_HOME", "")
    java = "java"
    if java_home:
        java = str(Path(java_home) / "bin" / "java")
    launcher = extra.get("jdtls_launcher_path")
    config_dir = extra.get("jdtls_config_dir")
    data_dir = extra.get("workspace_data_dir") or str(Path(project_root) / ".lsp_workspace")
    if not launcher or not config_dir:
        raise ValueError("Java LSP 需要 extra.jdtls_launcher_path 与 extra.jdtls_config_dir")
    return [
        java,
        "-jar", launcher,
        "-configuration", config_dir,
        "-data", data_dir,
    ]


class LSPSessionManager:
    """LSP 会话管理器：按 project_root+language 复用进程。"""

    def __init__(
        self,
        init_timeout: float = DEFAULT_INIT_TIMEOUT,
        request_timeout: float = DEFAULT_REQUEST_TIMEOUT,
    ):
        self._sessions: dict[tuple[str, str], LSPClient] = {}
        self._init_timeout = init_timeout
        self._request_timeout = request_timeout

    def _key(self, project_root: str, language: str) -> tuple[str, str]:
        return (str(Path(project_root).resolve()), language)

    async def start(
        self,
        language: str,
        project_root: str,
        workspace_name: str | None = None,
        extra: dict | None = None,
    ) -> tuple[bool, str]:
        """
        启动 LSP 会话。若已存在则返回 (True, "已启动")。
        返回 (False, error_msg) 表示失败。
        """
        key = self._key(project_root, language)
        if key in self._sessions:
            return True, "已启动"

        extra = extra or {}
        try:
            if language == "python":
                cmd = _get_python_command(extra)
            elif language == "java":
                cmd = _get_java_command(project_root, extra)
            else:
                return False, f"不支持的语言: {language}"
        except ValueError as e:
            return False, str(e)

        try:
            proc = await asyncio.create_subprocess_exec(
                *cmd,
                cwd=project_root,
                stdin=asyncio.subprocess.PIPE,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.DEVNULL,  # 避免 stderr 管道满导致阻塞
            )
            client = LSPClient(project_root, language, proc, timeout=self._request_timeout)
            t0 = time.perf_counter()
            await asyncio.wait_for(client.initialize(), timeout=self._init_timeout)
            init_ms = int((time.perf_counter() - t0) * 1000)
            self._sessions[key] = client
            msg = f"已启动（初始化耗时 {init_ms}ms）" if init_ms > 500 else "已启动"
            if language == "java" and init_ms > 3000:
                logger.info("[LSP] JDT LS 初始化耗时 %dms，project_root=%s", init_ms, project_root)
            return True, msg
        except asyncio.TimeoutError:
            logger.warning("[LSP] 启动超时 language=%s init_timeout=%s", language, self._init_timeout)
            return False, f"LSP 启动超时（init_timeout={self._init_timeout}s）"
        except Exception as e:
            err_msg = str(e) or type(e).__name__
            logger.warning("[LSP] 启动失败 language=%s: %s", language, err_msg, exc_info=True)
            return False, f"LSP 启动失败: {err_msg}"

    async def stop(self, language: str, project_root: str) -> None:
        """关闭会话。"""
        key = self._key(project_root, language)
        if key in self._sessions:
            client = self._sessions.pop(key)
            await client.shutdown()

    def get(self, language: str, project_root: str) -> LSPClient | None:
        """获取已存在的会话。"""
        return self._sessions.get(self._key(project_root, language))

    async def workspace_symbol(
        self, language: str, project_root: str, query: str, limit: int = 20
    ) -> list[SymbolLocation]:
        client = self.get(language, project_root)
        if not client:
            raise RuntimeError("LSP 会话未启动，请先调用 lsp.start")
        return await client.workspace_symbol(query, limit)

    async def definition(
        self, language: str, project_root: str, file_path: str, line: int, character: int
    ) -> list[CodeLocation]:
        client = self.get(language, project_root)
        if not client:
            raise RuntimeError("LSP 会话未启动，请先调用 lsp.start")
        return await client.definition(file_path, line, character)

    async def references(
        self,
        language: str,
        project_root: str,
        file_path: str,
        line: int,
        character: int,
        include_declaration: bool = False,
        limit: int = 50,
    ) -> list[CodeLocation]:
        client = self.get(language, project_root)
        if not client:
            raise RuntimeError("LSP 会话未启动，请先调用 lsp.start")
        return await client.references(file_path, line, character, include_declaration, limit)

    async def hover(
        self, language: str, project_root: str, file_path: str, line: int, character: int
    ) -> HoverInfo | None:
        client = self.get(language, project_root)
        if not client:
            raise RuntimeError("LSP 会话未启动，请先调用 lsp.start")
        return await client.hover(file_path, line, character)

    async def document_symbols(self, language: str, project_root: str, file_path: str) -> list[dict]:
        client = self.get(language, project_root)
        if not client:
            raise RuntimeError("LSP 会话未启动，请先调用 lsp.start")
        return await client.document_symbols(file_path)
