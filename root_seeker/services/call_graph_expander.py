"""
方法级调用链展开：从已收集的代码片段中解析方法调用关系，定位调用方/被调用方方法代码并加入证据。
支持迭代扩展直到达到上限或找全关联内容。

优化：
- 使用 Tree-sitter 精确解析方法调用关系（替代正则）
- 支持异步 Zoekt 客户端搜索方法名
- 添加缓存机制避免重复扫描
- 限制扫描范围（优先扫描 src/main、src 等常见目录）
"""
from __future__ import annotations

import asyncio
import hashlib
import logging
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from root_seeker.domain import EvidenceFile, EvidencePack
from root_seeker.providers.zoekt import ZoektClient

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class CallGraphExpanderConfig:
    """方法级调用链展开配置"""
    enabled: bool = False
    max_rounds: int = 2  # 最多迭代几轮
    max_methods_per_round: int = 5  # 每轮最多找几个方法
    max_total_methods: int = 15  # 总共最多找几个方法
    context_lines: int = 30  # 读取方法代码时的上下文行数
    use_tree_sitter: bool = True  # 使用 Tree-sitter 解析（更精确），否则用正则
    scan_limit_dirs: list[str] | None = None  # 限制扫描目录（如 ["src/main", "src"]），None 表示全仓库
    cache_size: int = 100  # 方法定位缓存大小（LRU）

    def get_scan_dirs(self) -> list[str]:
        """获取扫描目录列表（处理 None 默认值）"""
        return self.scan_limit_dirs if self.scan_limit_dirs is not None else ["src/main", "src", "app", "lib"]


@dataclass(frozen=True)
class MethodReference:
    """方法引用：类名.方法名 或 方法名"""
    class_name: str | None
    method_name: str
    file_path: str | None = None  # 如果已知文件路径
    line_number: int | None = None  # 如果已知行号


class CallGraphExpander:
    """从代码片段中解析方法调用关系，并扩展证据包"""

    def __init__(
        self,
        cfg: CallGraphExpanderConfig,
        zoekt_client: ZoektClient | None = None,
        tree_sitter_chunker: Any | None = None,
    ):
        """
        Args:
            cfg: 配置
            zoekt_client: 可选的异步 Zoekt 客户端，用于按方法名搜索
            tree_sitter_chunker: 可选的 TreeSitterChunker，用于精确解析方法调用
        """
        self._cfg = cfg
        self._zoekt_client = zoekt_client
        self._tree_sitter_chunker = tree_sitter_chunker
        # 方法定位缓存：method_key -> list[EvidenceFile]
        self._method_cache: dict[str, list[EvidenceFile]] = {}
        self._current_analysis_id: str = ""
        # 文件解析缓存：file_path -> (methods_definitions, method_calls)
        self._file_parse_cache: dict[str, tuple[list[MethodReference], list[MethodReference]]] = {}
        # v3.0.0：本轮展开的降级模式，供 evidence.notes 可见
        self._expand_degradations: set[str] = set()

    async def expand_evidence(
        self,
        *,
        evidence: EvidencePack,
        repo_local_dir: str,
        max_files: int,
        max_chars_total: int,
        max_chars_per_file: int,
        analysis_id: str | None = None,
    ) -> EvidencePack:
        """
        从证据包中的代码片段解析方法调用关系，定位并读取调用方/被调用方方法代码，迭代扩展证据。

        Args:
            evidence: 初始证据包（会被修改）
            repo_local_dir: 仓库本地目录
            max_files: 证据包最大文件数
            max_chars_total: 证据包最大总字符数
            max_chars_per_file: 单个文件最大字符数

        Returns:
            扩展后的证据包（原地修改）
        """
        if not self._cfg.enabled:
            logger.debug("[CallGraphExpander] 调用链展开未启用")
            return evidence

        self._expand_degradations = set()
        self._current_analysis_id = analysis_id or ""
        base = Path(repo_local_dir)
        if not base.exists() or not base.is_dir():
            logger.warning(f"[CallGraphExpander] 仓库目录不存在：{repo_local_dir}")
            return evidence

        logger.info(f"[CallGraphExpander] 开始展开调用链，repo={repo_local_dir}, 初始证据文件数={len(evidence.files)}")
        seen_methods: set[tuple[str | None, str]] = set()  # (class_name, method_name)
        seen_files: set[str] = set()  # file_path
        total_chars = sum(len(f.content) for f in evidence.files)
        total_methods_added = 0

        # 初始化：从现有证据中提取已见过的方法
        for ef in evidence.files:
            if ef.file_path:
                seen_files.add(ef.file_path)
            if ef.source in ("stacktrace", "zoekt", "qdrant"):
                # 从代码片段中提取方法定义（已存在的方法）
                methods = await self._extract_method_definitions(ef.content, ef.file_path or "", repo_local_dir)
                for m in methods:
                    seen_methods.add((m.class_name, m.method_name))
        logger.debug(f"[CallGraphExpander] 初始化完成，已识别 {len(seen_methods)} 个方法，{len(seen_files)} 个文件")

        # 迭代扩展
        for round_num in range(self._cfg.max_rounds):
            if total_methods_added >= self._cfg.max_total_methods:
                logger.info(f"[CallGraphExpander] 已达到最大方法数限制（{self._cfg.max_total_methods}），停止展开")
                self._expand_degradations.add("scan_truncated")
                break
            if len(evidence.files) >= max_files:
                break

            # 从当前证据中提取方法调用
            new_methods: list[MethodReference] = []
            for ef in evidence.files:
                if ef.source in ("stacktrace", "zoekt", "qdrant", "call_graph"):
                    calls = await self._extract_method_calls(ef.content, ef.file_path or "", repo_local_dir)
                    for call in calls:
                        key = (call.class_name, call.method_name)
                        if key not in seen_methods:
                            seen_methods.add(key)
                            new_methods.append(call)
                            if len(new_methods) >= self._cfg.max_methods_per_round:
                                break
                if len(new_methods) >= self._cfg.max_methods_per_round:
                    break

            if not new_methods:
                logger.debug(f"[CallGraphExpander] 第 {round_num + 1} 轮未发现新方法，停止迭代")
                break  # 没有新发现，停止迭代

            logger.info(f"[CallGraphExpander] 第 {round_num + 1} 轮发现 {len(new_methods)} 个新方法调用")
            # 定位并读取这些方法的代码（异步批量处理）
            added_this_round = 0
            tasks = []
            for method_ref in new_methods[: self._cfg.max_methods_per_round]:
                if total_methods_added >= self._cfg.max_total_methods:
                    break
                if len(evidence.files) >= max_files:
                    break
                tasks.append(
                    self._locate_method_code_async(
                        method_ref=method_ref,
                        repo_local_dir=repo_local_dir,
                        seen_files=seen_files,
                    )
                )

            if tasks:
                logger.debug(f"[CallGraphExpander] 并行定位 {len(tasks)} 个方法的代码")
                results_list = await asyncio.gather(*tasks, return_exceptions=True)
                for method_files in results_list:
                    if isinstance(method_files, Exception):
                        logger.debug(f"[CallGraphExpander] 方法定位失败：{method_files}")
                        continue
                    for ef in method_files:
                        if len(evidence.files) >= max_files:
                            break
                        if total_chars + len(ef.content) > max_chars_total:
                            break
                        if len(ef.content) > max_chars_per_file:
                            ef = ef.model_copy(update={"content": ef.content[:max_chars_per_file]})
                        if ef.file_path:
                            seen_files.add(ef.file_path)
                        evidence.files.append(ef)
                        total_chars += len(ef.content)
                        total_methods_added += 1
                        added_this_round += 1
                        if total_methods_added >= self._cfg.max_total_methods:
                            break

            if added_this_round == 0:
                logger.debug(f"[CallGraphExpander] 第 {round_num + 1} 轮未找到新代码，停止迭代")
                break  # 本轮没有找到新代码，停止迭代

            logger.info(f"[CallGraphExpander] 第 {round_num + 1} 轮完成，新增 {added_this_round} 个方法代码片段，累计 {total_methods_added} 个")
            if round_num == 0 and added_this_round > 0:
                evidence.notes.append(f"方法级调用链展开：第1轮找到 {added_this_round} 个关联方法。")
            elif added_this_round > 0:
                evidence.notes.append(f"方法级调用链展开：第{round_num + 1}轮找到 {added_this_round} 个关联方法。")

        if total_methods_added > 0:
            evidence.notes.append(f"方法级调用链展开：共扩展 {total_methods_added} 个关联方法代码片段。")
            logger.info(f"[CallGraphExpander] 调用链展开完成，共扩展 {total_methods_added} 个方法，最终证据文件数={len(evidence.files)}")
        else:
            logger.debug("[CallGraphExpander] 调用链展开未找到新方法")

        if self._expand_degradations:
            deg = sorted(self._expand_degradations)
            evidence.notes.append(f"[degraded_modes] {', '.join(deg)}")
            evidence.notes.append(f"[risk_flags] {deg}")

        return evidence

    async def _extract_method_calls(
        self, code: str, file_path: str, repo_local_dir: str
    ) -> list[MethodReference]:
        """从代码片段中提取方法调用（谁被调用了）"""
        # 使用缓存
        cache_key = f"{file_path}:{hashlib.md5(code.encode()).hexdigest()[:16]}"
        if cache_key in self._file_parse_cache:
            _, calls = self._file_parse_cache[cache_key]
            return calls

        calls: list[MethodReference] = []

        # 优先使用 Tree-sitter 解析（更精确）
        if self._cfg.use_tree_sitter and self._tree_sitter_chunker and file_path:
            calls = await self._extract_calls_with_tree_sitter(code, file_path, repo_local_dir)
            if not calls:
                self._expand_degradations.add("treesitter_fallback")

        # 如果 Tree-sitter 未启用或未找到，回退到正则
        if not calls:
            calls = self._extract_calls_with_regex(code, file_path)

        # 更新缓存
        if len(self._file_parse_cache) < self._cfg.cache_size:
            self._file_parse_cache[cache_key] = ([], calls)

        return calls

    async def _extract_method_definitions(
        self, code: str, file_path: str, repo_local_dir: str
    ) -> list[MethodReference]:
        """从代码片段中提取方法定义（哪些方法存在）"""
        # 使用缓存
        cache_key = f"{file_path}:{hashlib.md5(code.encode()).hexdigest()[:16]}"
        if cache_key in self._file_parse_cache:
            methods, _ = self._file_parse_cache[cache_key]
            return methods

        methods: list[MethodReference] = []

        # 优先使用 Tree-sitter 解析
        if self._cfg.use_tree_sitter and self._tree_sitter_chunker and file_path:
            methods = await self._extract_definitions_with_tree_sitter(code, file_path, repo_local_dir)
            if not methods:
                self._expand_degradations.add("treesitter_fallback")

        # 如果 Tree-sitter 未启用或未找到，回退到正则
        if not methods:
            methods = self._extract_definitions_with_regex(code, file_path)

        # 更新缓存
        if len(self._file_parse_cache) < self._cfg.cache_size:
            self._file_parse_cache[cache_key] = (methods, [])

        return methods

    async def _extract_calls_with_tree_sitter(
        self, code: str, file_path: str, repo_local_dir: str
    ) -> list[MethodReference]:
        """使用 Tree-sitter 解析方法调用"""
        calls: list[MethodReference] = []
        try:
            path = Path(repo_local_dir) / file_path.lstrip("/")
            if not path.exists():
                return calls

            lang = self._detect_language(path)
            if lang is None:
                return calls

            source = path.read_bytes()
            parser = self._get_tree_sitter_parser(lang)
            tree = parser.parse(source)
            root = tree.root_node

            # 遍历 AST 查找方法调用节点
            stack = [root]
            seen: set[tuple[str | None, str]] = set()

            while stack:
                node = stack.pop()
                # Java: method_invocation
                # Python: call
                if node.type in ("method_invocation", "call"):
                    method_ref = self._parse_call_node(node, source, lang, file_path)
                    if method_ref:
                        key = (method_ref.class_name, method_ref.method_name)
                        if key not in seen:
                            seen.add(key)
                            calls.append(method_ref)

                for child in reversed(node.children):
                    stack.append(child)

        except Exception as e:
            aid = getattr(self, "_current_analysis_id", "") or ""
            logger.warning(
                "[CallGraphExpander] 解析方法调用降级 analysis_id=%s tool=extract_calls exception=%s file=%s",
                aid, type(e).__name__, file_path,
            )
            self._expand_degradations.add("extract_calls_failed")

        return calls

    async def _extract_definitions_with_tree_sitter(
        self, code: str, file_path: str, repo_local_dir: str
    ) -> list[MethodReference]:
        """使用 Tree-sitter 解析方法定义"""
        methods: list[MethodReference] = []
        try:
            path = Path(repo_local_dir) / file_path.lstrip("/")
            if not path.exists():
                return methods

            lang = self._detect_language(path)
            if lang is None:
                return methods

            source = path.read_bytes()
            parser = self._get_tree_sitter_parser(lang)
            tree = parser.parse(source)
            root = tree.root_node

            # Java: method_declaration
            # Python: function_definition
            node_types = {"method_declaration", "function_definition"} if lang == "java" else {"function_definition"}
            stack = [root]
            seen: set[tuple[str | None, str]] = set()

            while stack:
                node = stack.pop()
                if node.type in node_types:
                    method_ref = self._parse_definition_node(node, source, lang, file_path, root)
                    if method_ref:
                        key = (method_ref.class_name, method_ref.method_name)
                        if key not in seen:
                            seen.add(key)
                            methods.append(method_ref)

                for child in reversed(node.children):
                    stack.append(child)

        except Exception as e:
            aid = getattr(self, "_current_analysis_id", "") or ""
            logger.warning(
                "[CallGraphExpander] 解析方法定义降级 analysis_id=%s tool=extract_definitions exception=%s file=%s",
                aid, type(e).__name__, file_path,
            )
            self._expand_degradations.add("extract_definitions_failed")

        return methods

    def _parse_call_node(self, node: Any, source: bytes, lang: str, file_path: str) -> MethodReference | None:
        """从 Tree-sitter 调用节点解析方法引用"""
        try:
            method_name = None
            class_name = None

            if lang == "java":
                # method_invocation: object.methodName(...)
                # 查找 name 或 identifier 子节点
                for child in node.children:
                    if child.type == "identifier":
                        method_name = source[child.start_byte : child.end_byte].decode("utf-8", errors="replace")
                    elif child.type == "object" or child.type == "primary":
                        # 尝试提取类名
                        obj_text = source[child.start_byte : child.end_byte].decode("utf-8", errors="replace")
                        if "." in obj_text:
                            parts = obj_text.split(".")
                            if len(parts) >= 2:
                                class_name = parts[-2]

            elif lang == "python":
                # call: function(...)
                for child in node.children:
                    if child.type == "attribute":
                        # obj.method(...)
                        attr_children = list(child.children)
                        if len(attr_children) >= 2:
                            method_name = source[attr_children[1].start_byte : attr_children[1].end_byte].decode(
                                "utf-8", errors="replace"
                            )
                            obj_text = source[attr_children[0].start_byte : attr_children[0].end_byte].decode(
                                "utf-8", errors="replace"
                            )
                            if "." in obj_text:
                                parts = obj_text.split(".")
                                if len(parts) >= 2:
                                    class_name = parts[-2]
                    elif child.type == "identifier":
                        # function(...)
                        method_name = source[child.start_byte : child.end_byte].decode("utf-8", errors="replace")

            if method_name and len(method_name) >= 2:
                # 过滤关键字
                if method_name.lower() in ("if", "for", "while", "def", "class", "import", "return", "print", "new"):
                    return None
                return MethodReference(class_name=class_name, method_name=method_name, file_path=file_path)

        except Exception as e:
            aid = getattr(self, "_current_analysis_id", "") or ""
            logger.debug(
                "[CallGraphExpander] 解析调用节点降级 analysis_id=%s tool=parse_call_node exception=%s",
                aid, type(e).__name__,
            )
        return None

    def _parse_definition_node(
        self, node: Any, source: bytes, lang: str, file_path: str, root: Any
    ) -> MethodReference | None:
        """从 Tree-sitter 定义节点解析方法引用"""
        try:
            method_name = None
            class_name = None

            # 提取方法名
            for child in node.children:
                if child.type in ("identifier", "name"):
                    method_name = source[child.start_byte : child.end_byte].decode("utf-8", errors="replace")
                    break

            if not method_name or len(method_name) < 2:
                return None

            # 提取类名（向上查找 class_declaration）
            if lang == "java":
                current = node
                while current and current != root:
                    current = current.parent
                    if current and current.type == "class_declaration":
                        for ch in current.children:
                            if ch.type == "identifier":
                                class_name = source[ch.start_byte : ch.end_byte].decode("utf-8", errors="replace")
                                break
                        break
            elif lang == "python":
                current = node
                while current and current != root:
                    current = current.parent
                    if current and current.type == "class_definition":
                        for ch in current.children:
                            if ch.type == "identifier":
                                class_name = source[ch.start_byte : ch.end_byte].decode("utf-8", errors="replace")
                                break
                        break

            return MethodReference(class_name=class_name, method_name=method_name, file_path=file_path)

        except Exception as e:
            aid = getattr(self, "_current_analysis_id", "") or ""
            logger.debug(
                "[CallGraphExpander] 解析定义节点降级 analysis_id=%s tool=parse_definition_node exception=%s",
                aid, type(e).__name__,
            )
        return None

    def _extract_calls_with_regex(self, code: str, file_path: str) -> list[MethodReference]:
        """使用正则提取方法调用（回退方案）"""
        calls: list[MethodReference] = []
        seen: set[tuple[str | None, str]] = set()

        # Java: obj.methodName(, this.methodName(, ClassName.methodName(
        for m in re.finditer(r"(?:(\w+(?:\.\w+)*)\.)?(\w+)\s*\(", code):
            class_or_obj = m.group(1)
            method_name = m.group(2)
            if not method_name or len(method_name) < 2:
                continue
            if method_name.lower() in ("if", "for", "while", "switch", "catch", "return", "new", "class", "import"):
                continue
            if class_or_obj and class_or_obj.lower() in ("string", "int", "long", "boolean", "void", "null"):
                continue

            class_name = None
            if class_or_obj and "." in class_or_obj:
                parts = class_or_obj.split(".")
                if len(parts) >= 2:
                    class_name = parts[-2]
            elif class_or_obj:
                class_name = class_or_obj

            key = (class_name, method_name)
            if key not in seen:
                seen.add(key)
                calls.append(MethodReference(class_name=class_name, method_name=method_name, file_path=file_path))

        # Python: obj.method_name(, module.function_name(
        for m in re.finditer(r"(?:(\w+(?:\.\w+)*)\.)?(\w+)\s*\(", code):
            module_or_obj = m.group(1)
            func_name = m.group(2)
            if not func_name or len(func_name) < 2:
                continue
            if func_name.lower() in ("if", "for", "while", "def", "class", "import", "from", "return", "print"):
                continue

            class_name = None
            if module_or_obj:
                parts = module_or_obj.split(".")
                if len(parts) >= 2:
                    class_name = parts[-2]

            key = (class_name, func_name)
            if key not in seen:
                seen.add(key)
                calls.append(MethodReference(class_name=class_name, method_name=func_name, file_path=file_path))

        return calls

    def _extract_definitions_with_regex(self, code: str, file_path: str) -> list[MethodReference]:
        """使用正则提取方法定义（回退方案）"""
        methods: list[MethodReference] = []
        seen: set[tuple[str | None, str]] = set()

        # Java: public/private/protected ... methodName(, static ... methodName(
        for m in re.finditer(r"(?:public|private|protected|static|\s)+\s*(?:\w+\s+)*(\w+)\s*\([^)]*\)\s*\{", code):
            method_name = m.group(1)
            if method_name and len(method_name) >= 2:
                class_match = re.search(r"class\s+(\w+)", code[: m.start()])
                class_name = class_match.group(1) if class_match else None
                key = (class_name, method_name)
                if key not in seen:
                    seen.add(key)
                    methods.append(MethodReference(class_name=class_name, method_name=method_name, file_path=file_path))

        # Python: def function_name(, def method_name(self,
        for m in re.finditer(r"def\s+(\w+)\s*\(", code):
            func_name = m.group(1)
            if func_name and len(func_name) >= 2:
                class_match = re.search(r"class\s+(\w+)", code[: m.start()])
                class_name = class_match.group(1) if class_match else None
                key = (class_name, func_name)
                if key not in seen:
                    seen.add(key)
                    methods.append(MethodReference(class_name=class_name, method_name=func_name, file_path=file_path))

        return methods

    async def _locate_method_code_async(
        self,
        *,
        method_ref: MethodReference,
        repo_local_dir: str,
        seen_files: set[str],
    ) -> list[EvidenceFile]:
        """异步定位方法代码所在文件与行号"""
        # 检查缓存
        cache_key = f"{method_ref.class_name or ''}:{method_ref.method_name}"
        if cache_key in self._method_cache:
            cached = [
                ef for ef in self._method_cache[cache_key] if ef.file_path not in seen_files
            ]
            if cached:
                return cached[:2]  # 最多返回2个

        base = Path(repo_local_dir)
        results: list[EvidenceFile] = []

        # 策略1: 已知文件路径
        if method_ref.file_path:
            path = base / method_ref.file_path.lstrip("/")
            if path.exists() and path.is_file():
                method_code = await self._find_method_in_file_async(
                    path=path,
                    method_name=method_ref.method_name,
                    class_name=method_ref.class_name,
                    repo_local_dir=repo_local_dir,
                )
                if method_code:
                    results.append(method_code)
                    self._update_cache(cache_key, results)
                    return results

        # 策略2: 用 Zoekt 异步搜索（如果可用）
        if self._zoekt_client:
            query = method_ref.method_name
            if method_ref.class_name:
                query = f"{method_ref.class_name} {method_ref.method_name}"
            try:
                hits = await self._zoekt_client.search(query=query, max_matches=5)
                for hit in hits[:3]:
                    if hit.file_path:
                        file_path = hit.file_path.lstrip("/")
                        if file_path in seen_files:
                            continue
                        path = base / file_path
                        if path.exists() and path.is_file():
                            method_code = await self._find_method_in_file_async(
                                path=path,
                                method_name=method_ref.method_name,
                                class_name=method_ref.class_name,
                                repo_local_dir=repo_local_dir,
                                preferred_line=hit.line_number,
                            )
                            if method_code:
                                results.append(method_code)
                                if len(results) >= 2:
                                    break
            except Exception as e:
                self._expand_degradations.add("zoekt_failed")
                logger.debug("[CallGraphExpander] Zoekt 搜索失败: %s", type(e).__name__)

        # 策略3: 限制范围扫描（优先常见目录）
        if not results:
            scan_dirs = self._cfg.get_scan_dirs()
            for dir_pattern in scan_dirs:
                if len(results) >= 2:
                    break
                for path in base.rglob(f"{dir_pattern}/**/*.java"):
                    if str(path.relative_to(base)) in seen_files:
                        continue
                    method_code = await self._find_method_in_file_async(
                        path=path,
                        method_name=method_ref.method_name,
                        class_name=method_ref.class_name,
                        repo_local_dir=repo_local_dir,
                    )
                    if method_code:
                        results.append(method_code)
                        if len(results) >= 2:
                            break
                if not results:
                    for path in base.rglob(f"{dir_pattern}/**/*.py"):
                        if str(path.relative_to(base)) in seen_files:
                            continue
                        method_code = await self._find_method_in_file_async(
                            path=path,
                            method_name=method_ref.method_name,
                            class_name=method_ref.class_name,
                            repo_local_dir=repo_local_dir,
                        )
                        if method_code:
                            results.append(method_code)
                            if len(results) >= 2:
                                break

        # 如果限制目录未找到，回退到全仓库扫描（但限制文件数）
        if not results:
            file_count = 0
            max_scan_files = 200  # 限制扫描文件数
            scan_truncated = False
            for path in base.rglob("*.java"):
                if file_count >= max_scan_files:
                    scan_truncated = True
                    break
                if str(path.relative_to(base)) in seen_files:
                    continue
                file_count += 1
                method_code = await self._find_method_in_file_async(
                    path=path,
                    method_name=method_ref.method_name,
                    class_name=method_ref.class_name,
                    repo_local_dir=repo_local_dir,
                )
                if method_code:
                    results.append(method_code)
                    if len(results) >= 2:
                        break
            if scan_truncated:
                self._expand_degradations.add("scan_truncated")
            if not results:
                file_count = 0
                for path in base.rglob("*.py"):
                    if file_count >= max_scan_files:
                        scan_truncated = True
                        break
                    if str(path.relative_to(base)) in seen_files:
                        continue
                    file_count += 1
                    method_code = await self._find_method_in_file_async(
                        path=path,
                        method_name=method_ref.method_name,
                        class_name=method_ref.class_name,
                        repo_local_dir=repo_local_dir,
                    )
                    if method_code:
                        results.append(method_code)
                        if len(results) >= 2:
                            break
            if scan_truncated:
                self._expand_degradations.add("scan_truncated")

        self._update_cache(cache_key, results)
        return results

    def _update_cache(self, cache_key: str, results: list[EvidenceFile]) -> None:
        """更新方法定位缓存"""
        if len(self._method_cache) >= self._cfg.cache_size:
            # 简单 LRU：删除最旧的（这里简化处理，删除第一个）
            if self._method_cache:
                first_key = next(iter(self._method_cache))
                del self._method_cache[first_key]
        self._method_cache[cache_key] = results

    async def _find_method_in_file_async(
        self,
        *,
        path: Path,
        method_name: str,
        class_name: str | None,
        repo_local_dir: str,
        preferred_line: int | None = None,
    ) -> EvidenceFile | None:
        """异步在文件中查找方法定义并返回代码片段"""
        try:
            lines = await asyncio.to_thread(path.read_text, encoding="utf-8", errors="replace")
            lines_list = lines.splitlines()
        except Exception:
            return None

        file_path = str(path.relative_to(Path(repo_local_dir)))
        is_java = path.suffix == ".java"
        is_python = path.suffix == ".py"

        # 如果指定了 preferred_line，优先在该行附近查找
        search_start = 0
        search_end = len(lines_list)
        if preferred_line and 1 <= preferred_line <= len(lines_list):
            search_start = max(0, preferred_line - 50)
            search_end = min(len(lines_list), preferred_line + 50)

        # Java: public/private ... returnType methodName(...
        if is_java:
            pattern = re.compile(
                r"(?:public|private|protected|static|\s)+\s*(?:\w+\s+)*" + re.escape(method_name) + r"\s*\(",
                re.IGNORECASE,
            )
            for i in range(search_start, search_end):
                if pattern.search(lines_list[i]):
                    start_line = i + 1
                    end_line = self._find_method_end(lines_list, start_line - 1, is_java=True)
                    if end_line > start_line:
                        content_lines = lines_list[
                            max(0, start_line - 1 - self._cfg.context_lines) : end_line + self._cfg.context_lines
                        ]
                        content = "\n".join(content_lines)
                        return EvidenceFile(
                            repo_local_dir=repo_local_dir,
                            file_path=file_path,
                            start_line=max(1, start_line - self._cfg.context_lines),
                            end_line=end_line + self._cfg.context_lines,
                            content=content,
                            source="call_graph",
                        )

        # Python: def method_name(self, ...) 或 def function_name(...
        if is_python:
            pattern = re.compile(r"def\s+" + re.escape(method_name) + r"\s*\(", re.IGNORECASE)
            for i in range(search_start, search_end):
                if pattern.search(lines_list[i]):
                    start_line = i + 1
                    end_line = self._find_method_end(lines_list, start_line - 1, is_java=False)
                    if end_line > start_line:
                        content_lines = lines_list[
                            max(0, start_line - 1 - self._cfg.context_lines) : end_line + self._cfg.context_lines
                        ]
                        content = "\n".join(content_lines)
                        return EvidenceFile(
                            repo_local_dir=repo_local_dir,
                            file_path=file_path,
                            start_line=max(1, start_line - self._cfg.context_lines),
                            end_line=end_line + self._cfg.context_lines,
                            content=content,
                            source="call_graph",
                        )

        return None

    def _find_method_end(self, lines: list[str], start_idx: int, *, is_java: bool) -> int:
        """找到方法结束行号（简单版：基于缩进或大括号）"""
        if start_idx >= len(lines):
            return start_idx + 1

        if is_java:
            brace_count = 0
            for i in range(start_idx, min(len(lines), start_idx + 200)):
                line = lines[i]
                brace_count += line.count("{") - line.count("}")
                if brace_count == 0 and i > start_idx:
                    return i + 1
            return min(len(lines), start_idx + 50)
        else:
            start_indent = len(lines[start_idx]) - len(lines[start_idx].lstrip())
            for i in range(start_idx + 1, min(len(lines), start_idx + 200)):
                if not lines[i].strip():
                    continue
                indent = len(lines[i]) - len(lines[i].lstrip())
                if indent <= start_indent and lines[i].strip():
                    return i
            return min(len(lines), start_idx + 50)

    def _detect_language(self, path: Path) -> str | None:
        """检测文件语言"""
        if path.suffix == ".py":
            return "python"
        if path.suffix == ".java":
            return "java"
        return None

    def _get_tree_sitter_parser(self, lang: str) -> Any:
        """获取 Tree-sitter parser"""
        if not self._tree_sitter_chunker:
            raise ValueError("Tree-sitter chunker not provided")
        # TreeSitterChunker 有 _get_parser 方法
        return self._tree_sitter_chunker._get_parser(lang)
