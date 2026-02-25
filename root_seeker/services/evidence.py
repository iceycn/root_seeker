from __future__ import annotations

import logging
import re
from dataclasses import dataclass
from pathlib import Path

from root_seeker.domain import EvidenceFile, EvidencePack, ZoektHit

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class EvidenceLimits:
    max_files: int = 12
    max_chars_total: int = 160_000
    max_chars_per_file: int = 24_000
    context_lines: int = 30


class EvidenceBuilder:
    def __init__(self, limits: EvidenceLimits):
        self._limits = limits

    def build(
        self,
        *,
        repo_local_dir: str,
        zoekt_hits: list[ZoektHit],
        vector_hits: list[dict] | None,
        level: str,
        error_log: str = "",
    ) -> EvidencePack:
        logger.debug(f"[EvidenceBuilder] 开始构建证据包，repo={repo_local_dir}, level={level}, zoekt_hits={len(zoekt_hits)}, vector_hits={len(vector_hits) if vector_hits else 0}")
        files: list[EvidenceFile] = []
        notes: list[str] = []
        total_chars = 0

        def append_file(ef: EvidenceFile) -> bool:
            nonlocal total_chars
            if len(files) >= self._limits.max_files:
                return False
            content = ef.content
            if len(content) > self._limits.max_chars_per_file:
                content = content[: self._limits.max_chars_per_file]
                ef = ef.model_copy(update={"content": content})
            if total_chars + len(content) > self._limits.max_chars_total:
                return False
            total_chars += len(content)
            files.append(ef)
            return True

        if error_log and level == "L3":
            for ef in self._collect_evidence_from_stack_trace(repo_local_dir=repo_local_dir, error_log=error_log):
                if not append_file(ef):
                    break
            # 当错误涉及 API 参数（如 startTime）时，收集 Request/DTO 类定义，便于识别「方法/接口使用错误」
            for ef in self._collect_request_dto_evidence(
                repo_local_dir=repo_local_dir,
                existing_content="\n".join(f.content for f in files),
                error_log=error_log,
            ):
                if any(f.file_path == ef.file_path for f in files):
                    continue
                if not append_file(ef):
                    break

        pack1 = self.build_from_zoekt_hits(repo_local_dir=repo_local_dir, hits=zoekt_hits, level=level)
        for ef in pack1.files:
            append_file(ef)
        notes.extend(pack1.notes)

        if vector_hits:
            for vh in vector_hits:
                payload = vh.get("payload") or {}
                file_path = payload.get("file_path")
                if not isinstance(file_path, str) or not file_path:
                    continue
                if any(f.file_path == file_path and f.source == "qdrant" for f in files):
                    continue
                start_line = payload.get("start_line")
                end_line = payload.get("end_line")

                expanded = None
                if level == "L3" and isinstance(start_line, int) and isinstance(end_line, int):
                    expanded = self._read_file_region(
                        repo_local_dir=repo_local_dir,
                        file_path=file_path,
                        start_line=max(1, start_line - 20),
                        end_line=end_line + 20,
                    )
                if expanded is None:
                    content = payload.get("text")
                    if not isinstance(content, str) or not content.strip():
                        continue
                    expanded = EvidenceFile(
                        repo_local_dir=repo_local_dir,
                        file_path=file_path,
                        start_line=start_line if isinstance(start_line, int) else None,
                        end_line=end_line if isinstance(end_line, int) else None,
                        content=content,
                        source="qdrant",
                    )

                if not append_file(expanded.model_copy(update={"source": "qdrant"})):
                    break

        if level == "L3":
            code_count = sum(1 for f in files if f.source in ("stacktrace", "zoekt", "qdrant"))
            config_max = 4 if code_count > 0 else 12
            config_added = 0
            for ef in self._collect_build_config_files(repo_local_dir=repo_local_dir):
                if any(f.file_path == ef.file_path for f in files):
                    continue
                if config_added >= config_max:
                    break
                if append_file(ef):
                    config_added += 1

        if not files:
            notes.append("未收集到任何证据片段。")
            logger.warning(f"[EvidenceBuilder] 未收集到任何证据片段，repo={repo_local_dir}")
        else:
            logger.info(f"[EvidenceBuilder] 证据包构建完成，文件数={len(files)}, 总字符数={total_chars}, 来源分布={_count_sources(files)}")
        return EvidencePack(level=level, files=files, notes=notes)

    def build_from_zoekt_hits(self, *, repo_local_dir: str, hits: list[ZoektHit], level: str) -> EvidencePack:
        files: list[EvidenceFile] = []
        total_chars = 0

        seen: set[tuple[str, int | None]] = set()
        repo_base = Path(repo_local_dir).name
        for hit in hits:
            key = (hit.file_path, hit.line_number)
            if key in seen:
                continue
            seen.add(key)

            if len(files) >= self._limits.max_files:
                break

            file_path = hit.file_path.lstrip("/")
            if repo_base and file_path.startswith(repo_base + "/"):
                file_path = file_path[len(repo_base) + 1 :]
            # 安全验证：防止路径遍历攻击
            # 规范化路径并确保它在 repo_local_dir 内
            try:
                repo_path = Path(repo_local_dir).resolve()
                full_path = (repo_path / file_path).resolve()
                # 确保解析后的路径在仓库目录内（防止 ../ 攻击）
                if not str(full_path).startswith(str(repo_path)):
                    logger.warning(f"[EvidenceBuilder] 检测到路径遍历尝试，已忽略：{hit.file_path}")
                    continue
                path = full_path
            except (ValueError, OSError) as e:
                logger.warning(f"[EvidenceBuilder] 无效的文件路径，已忽略：{hit.file_path}, 错误：{e}")
                continue
            if not path.exists() or not path.is_file():
                continue

            start_line = None
            end_line = None
            content = path.read_text(encoding="utf-8", errors="replace").splitlines()

            if hit.line_number is not None and hit.line_number > 0:
                start_line = max(1, hit.line_number - self._limits.context_lines)
                end_line = min(len(content), hit.line_number + self._limits.context_lines)
                snippet_lines = content[start_line - 1 : end_line]
            else:
                snippet_lines = content[: min(len(content), 200)]
                start_line = 1
                end_line = len(snippet_lines)

            snippet = "\n".join(snippet_lines)
            if len(snippet) > self._limits.max_chars_per_file:
                snippet = snippet[: self._limits.max_chars_per_file]

            if total_chars + len(snippet) > self._limits.max_chars_total:
                break

            total_chars += len(snippet)
            files.append(
                EvidenceFile(
                    repo_local_dir=repo_local_dir,
                    file_path=file_path,
                    start_line=start_line,
                    end_line=end_line,
                    content=snippet,
                    source="zoekt",
                )
            )

        notes: list[str] = []
        if not files and hits:
            notes.append(
                "未从Zoekt命中结果中读取到本地文件内容（可能仓库未镜像到本地、路径不匹配、或Zoekt未返回当前仓库命中）。"
            )

        return EvidencePack(level=level, files=files, notes=notes)

    def append_vector_hits_from_repo(
        self,
        pack: EvidencePack,
        *,
        repo_local_dir: str,
        vector_hits: list[dict],
        max_add: int,
        level: str,
        service_name: str,
    ) -> None:
        """从关联服务对应仓库的向量检索结果中追加证据到 pack，用于跨仓库关联证据。"""
        if not vector_hits or max_add <= 0:
            return
        total_chars = sum(len(f.content) for f in pack.files)
        added = 0
        for vh in vector_hits:
            if added >= max_add or len(pack.files) >= self._limits.max_files:
                break
            payload = vh.get("payload") or {}
            file_path = payload.get("file_path")
            if not isinstance(file_path, str) or not file_path:
                continue
            if any(f.file_path == file_path and f.repo_local_dir == repo_local_dir for f in pack.files):
                continue
            start_line = payload.get("start_line")
            end_line = payload.get("end_line")
            expanded = None
            if level == "L3" and isinstance(start_line, int) and isinstance(end_line, int):
                expanded = self._read_file_region(
                    repo_local_dir=repo_local_dir,
                    file_path=file_path,
                    start_line=max(1, start_line - 20),
                    end_line=end_line + 20,
                )
            if expanded is not None:
                ef = expanded.model_copy(update={"source": "qdrant_cross_repo"})
            else:
                content = payload.get("text")
                if not isinstance(content, str) or not content.strip():
                    continue
                ef = EvidenceFile(
                    repo_local_dir=repo_local_dir,
                    file_path=file_path,
                    start_line=start_line if isinstance(start_line, int) else None,
                    end_line=end_line if isinstance(end_line, int) else None,
                    content=content[: self._limits.max_chars_per_file],
                    source="qdrant_cross_repo",
                )
            if total_chars + len(ef.content) > self._limits.max_chars_total:
                break
            if len(ef.content) > self._limits.max_chars_per_file:
                ef = ef.model_copy(update={"content": ef.content[: self._limits.max_chars_per_file]})
            pack.files.append(ef)
            total_chars += len(ef.content)
            added += 1
        if added > 0:
            pack.notes.append(f"已从关联服务 {service_name} 仓库追加 {added} 条向量检索证据。")

    def _collect_evidence_from_stack_trace(
        self, *, repo_local_dir: str, error_log: str
    ) -> list[EvidenceFile]:
        """从堆栈中解析 (文件名, 行号)，在本地仓库中查找并读取代码片段，作为链路关键证据。"""
        out: list[EvidenceFile] = []
        seen: set[tuple[str, int]] = set()
        base = Path(repo_local_dir)
        if not base.exists() or not base.is_dir():
            return out
        # Java: at ... (FileName.java:123)
        for m in re.finditer(r"\(([^()]+\.(?:java|py)):(\d+)\)", error_log):
            fname, line_str = m.group(1).strip(), m.group(2)
            line = int(line_str, 10)
            if (fname, line) in seen:
                continue
            seen.add((fname, line))
            fname_only = fname.split("/")[-1].split("\\")[-1]
            for path in base.rglob(fname_only):
                if not path.is_file() or path.suffix not in (".java", ".py"):
                    continue
                rel = str(path.relative_to(base))
                ef = self._read_file_region(
                    repo_local_dir=repo_local_dir,
                    file_path=rel,
                    start_line=max(1, line - self._limits.context_lines),
                    end_line=line + self._limits.context_lines,
                )
                if ef is not None:
                    out.append(ef.model_copy(update={"source": "stacktrace"}))
                break
        # Python: File "/path/to/file.py", line 123
        for m in re.finditer(r'File "([^"]+\.py)", line (\d+)', error_log):
            path_str, line_str = m.group(1), m.group(2)
            line = int(line_str, 10)
            fname_only = path_str.replace("\\", "/").split("/")[-1]
            if (fname_only, line) in seen:
                continue
            seen.add((fname_only, line))
            for path in base.rglob(fname_only):
                if not path.is_file():
                    continue
                rel = str(path.relative_to(base))
                ef = self._read_file_region(
                    repo_local_dir=repo_local_dir,
                    file_path=rel,
                    start_line=max(1, line - self._limits.context_lines),
                    end_line=line + self._limits.context_lines,
                )
                if ef is not None:
                    out.append(ef.model_copy(update={"source": "stacktrace"}))
                break
        return out

    def _read_file_region(
        self, *, repo_local_dir: str, file_path: str, start_line: int, end_line: int
    ) -> EvidenceFile | None:
        path = Path(repo_local_dir) / file_path.lstrip("/")
        if not path.exists() or not path.is_file():
            return None
        lines = path.read_text(encoding="utf-8", errors="replace").splitlines()
        start_line = max(1, start_line)
        end_line = min(len(lines), end_line)
        content = "\n".join(lines[start_line - 1 : end_line])
        return EvidenceFile(
            repo_local_dir=repo_local_dir,
            file_path=file_path,
            start_line=start_line,
            end_line=end_line,
            content=content,
            source="file",
        )

    def _collect_request_dto_evidence(
        self, *, repo_local_dir: str, existing_content: str, error_log: str
    ) -> list[EvidenceFile]:
        """当错误涉及 API 参数（如 startTime）时，收集 Request/DTO 类定义，便于识别「方法/接口使用错误」。"""
        out: list[EvidenceFile] = []
        base = Path(repo_local_dir)
        if not base.exists() or not base.is_dir():
            return out
        # 检测 API 参数错误模式：startTime、orderNo、endTime 等常为「接口混淆」信号
        api_param_pattern = r"startTime|orderNo|endTime|填写正确"
        if not re.search(api_param_pattern, error_log, re.I):
            return out
        # 从已有证据中提取 XxxRequest 类名
        request_classes: set[str] = set()
        for m in re.finditer(r"\b([A-Z][a-zA-Z0-9]*Request)\b", existing_content):
            request_classes.add(m.group(1))
        # 若涉及 PointCharging 且错误含 startTime，补充 PointValueAddRequest（点值添加接口的 Request，含 startTime）
        if "PointCharging" in existing_content and re.search(r"startTime|填写正确", error_log, re.I):
            request_classes.add("PointValueAddRequest")
        for class_name in request_classes:
            if class_name in ("BaseRequest", "HttpRequest"):
                continue
            for p in base.rglob(f"{class_name}.java"):
                if not p.is_file():
                    continue
                rel = str(p.relative_to(base))
                if any(rel == f.file_path for f in out):
                    continue
                content = p.read_text(encoding="utf-8", errors="replace")
                if len(content) > 4000:
                    content = content[:4000]
                out.append(
                    EvidenceFile(
                        repo_local_dir=repo_local_dir,
                        file_path=rel,
                        start_line=1,
                        end_line=min(100, len(content.splitlines())),
                        content=content,
                        source="request_dto",
                    )
                )
                if len(out) >= 3:  # 最多收集 3 个 Request 类
                    return out
                break
        return out

    def _collect_build_config_files(self, *, repo_local_dir: str) -> list[EvidenceFile]:
        base = Path(repo_local_dir)
        # 优先收集 application*.yml，便于排查 API 路径配置错误（如 point-charging-path 指向错误接口）
        patterns = [
            "application.yml",
            "application.yaml",
            "application-*.yml",
            "application-*.yaml",
            "bootstrap.yml",
            "bootstrap.yaml",
            "pom.xml",
            "build.gradle",
            "settings.gradle",
            "gradle.properties",
            "*.properties",
            "pyproject.toml",
            "requirements.txt",
            "setup.cfg",
            "setup.py",
        ]
        files: list[EvidenceFile] = []
        for pat in patterns:
            for p in base.rglob(pat):
                if not p.is_file():
                    continue
                rel = str(p.relative_to(base))
                content = p.read_text(encoding="utf-8", errors="replace")
                if len(content) > 8000:
                    content = content[:8000]
                files.append(
                    EvidenceFile(
                        repo_local_dir=repo_local_dir,
                        file_path=rel,
                        start_line=1,
                        end_line=min(400, len(content.splitlines())),
                        content=content,
                        source="config",
                    )
                )
        return files


def _count_sources(files: list[EvidenceFile]) -> dict[str, int]:
    """统计证据来源分布"""
    counts: dict[str, int] = {}
    for f in files:
        counts[f.source] = counts.get(f.source, 0) + 1
    return counts
