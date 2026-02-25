from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from tree_sitter import Language, Node, Parser


@dataclass(frozen=True)
class CodeChunk:
    repo_local_dir: str
    file_path: str
    language: str
    symbol: str | None
    start_line: int
    end_line: int
    text: str


class TreeSitterChunker:
    def __init__(self):
        self._parsers: dict[str, Parser] = {}

    def chunk_file(self, *, repo_local_dir: str, file_path: str) -> list[CodeChunk]:
        path = Path(repo_local_dir) / file_path.lstrip("/")
        if not path.exists() or not path.is_file():
            return []

        lang = self._detect_language(path)
        if lang is None:
            return []

        source = path.read_bytes()
        parser = self._get_parser(lang)
        tree = parser.parse(source)
        root = tree.root_node
        if lang == "python":
            nodes = self._collect_nodes(root, {"function_definition", "class_definition"})
        elif lang == "java":
            nodes = self._collect_nodes(root, {"method_declaration", "class_declaration"})
        else:
            nodes = []

        chunks: list[CodeChunk] = []
        for n in nodes:
            text = source[n.start_byte : n.end_byte].decode("utf-8", errors="replace")
            start_line = n.start_point[0] + 1
            end_line = n.end_point[0] + 1
            symbol = self._extract_symbol_name(n, source)
            if not text.strip():
                continue
            chunks.append(
                CodeChunk(
                    repo_local_dir=repo_local_dir,
                    file_path=file_path,
                    language=lang,
                    symbol=symbol,
                    start_line=start_line,
                    end_line=end_line,
                    text=text,
                )
            )
        return chunks

    def chunk_repo(self, *, repo_local_dir: str) -> list[CodeChunk]:
        base = Path(repo_local_dir)
        if not base.exists() or not base.is_dir():
            return []
        chunks: list[CodeChunk] = []
        for path in base.rglob("*"):
            if not path.is_file():
                continue
            if path.suffix not in {".py", ".java"}:
                continue
            rel = str(path.relative_to(base))
            try:
                chunks.extend(self.chunk_file(repo_local_dir=repo_local_dir, file_path=rel))
            except (OSError, ValueError, UnicodeDecodeError):
                continue
        return chunks

    def _detect_language(self, path: Path) -> str | None:
        if path.suffix == ".py":
            return "python"
        if path.suffix == ".java":
            return "java"
        return None

    def _get_parser(self, lang: str) -> Parser:
        parser = self._parsers.get(lang)
        if parser is not None:
            return parser
        language = self._get_language(lang)
        p = Parser()
        p.language = language
        self._parsers[lang] = p
        return p

    def _get_language(self, lang: str) -> Language:
        if lang == "python":
            import tree_sitter_python as tspython  # type: ignore

            return Language(tspython.language())
        if lang == "java":
            import tree_sitter_java as tsjava  # type: ignore

            return Language(tsjava.language())
        raise ValueError(f"Unsupported language: {lang}")

    def _collect_nodes(self, root: Node, types: set[str]) -> list[Node]:
        out: list[Node] = []
        stack = [root]
        while stack:
            n = stack.pop()
            if n.type in types:
                out.append(n)
                continue
            for ch in reversed(n.children):
                stack.append(ch)
        return out

    def _extract_symbol_name(self, node: Node, source: bytes) -> str | None:
        for ch in node.children:
            if ch.type == "identifier":
                return source[ch.start_byte : ch.end_byte].decode("utf-8", errors="replace")
            if ch.type == "name":
                return source[ch.start_byte : ch.end_byte].decode("utf-8", errors="replace")
        return None
