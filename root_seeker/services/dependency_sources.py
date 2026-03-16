"""依赖源码服务：将依赖坐标映射到可读源码（sources.jar / site-packages）。"""

from __future__ import annotations

import logging
import re
import subprocess
import zipfile
from dataclasses import dataclass
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)


@dataclass
class DepCoordinate:
    """依赖坐标。"""

    group_id: str | None = None
    artifact_id: str | None = None
    version: str | None = None
    name: str | None = None  # Python


@dataclass
class MaterializedSourceRoot:
    """物化后的源码根目录。"""

    coord: DepCoordinate
    path: str
    kind: str  # maven_sources | site_packages


@dataclass
class CodeLocation:
    """代码位置。"""

    file_path: str
    line: int
    character: int
    preview: str | None = None


def fetch_java_sources(project_root: str) -> list[DepCoordinate]:
    """获取 Java 项目依赖的源码坐标（通过解析 pom/gradle + 检查 ~/.m2）。"""
    from root_seeker.services.external_deps import parse_external

    result: list[DepCoordinate] = []
    deps = parse_external(project_root)
    if deps.ecosystem not in ("maven", "gradle"):
        return result
    for d in deps.direct_dependencies:
        if d.group_id and d.artifact_id:
            result.append(
                DepCoordinate(group_id=d.group_id, artifact_id=d.artifact_id, version=d.version)
            )
    return result


def materialize_maven_sources(coords: list[DepCoordinate]) -> list[MaterializedSourceRoot]:
    """将 Maven 坐标物化为源码路径（查找 ~/.m2 中的 *-sources.jar）。"""
    m2 = Path.home() / ".m2" / "repository"
    result: list[MaterializedSourceRoot] = []
    for c in coords or []:
        if not c.group_id or not c.artifact_id:
            continue
        rel = Path(c.group_id.replace(".", "/")) / c.artifact_id / (c.version or "")
        base = m2 / rel
        if not base.exists():
            continue
        for f in base.glob("*-sources.jar"):
            result.append(
                MaterializedSourceRoot(
                    coord=c,
                    path=str(f),
                    kind="maven_sources",
                )
            )
            break
    return result


def resolve_symbol_in_sources(
    symbol: str,
    source_roots: list[MaterializedSourceRoot],
    limit: int = 15,
) -> list[CodeLocation]:
    """在已物化源码（sources.jar）中搜索符号。基于 class/interface 名与文件内容匹配。"""
    if not symbol or not source_roots:
        return []
    # 提取简单类名（com.foo.Bar -> Bar）
    simple_name = symbol.split(".")[-1] if "." in symbol else symbol
    pattern = re.compile(
        rf"\b(?:class|interface|enum)\s+{re.escape(simple_name)}\b",
        re.MULTILINE,
    )
    result: list[CodeLocation] = []
    for root in source_roots:
        if len(result) >= limit:
            break
        path = Path(root.path)
        if not path.exists() or not path.suffix.lower() == ".jar":
            continue
        try:
            with zipfile.ZipFile(path, "r") as zf:
                for name in zf.namelist():
                    if not name.endswith(".java"):
                        continue
                    try:
                        data = zf.read(name)
                        text = data.decode("utf-8", errors="replace")
                    except Exception:
                        continue
                    for m in pattern.finditer(text):
                        line_num = text[: m.start()].count("\n") + 1
                        line_start = text.rfind("\n", 0, m.start()) + 1
                        line_end = text.find("\n", line_start)
                        if line_end < 0:
                            line_end = len(text)
                        preview = text[line_start:line_end].strip()[:120]
                        result.append(
                            CodeLocation(
                                file_path=f"{path}!/{name}",
                                line=line_num,
                                character=m.start() - line_start,
                                preview=preview,
                            )
                        )
                        if len(result) >= limit:
                            break
        except (zipfile.BadZipFile, OSError) as e:
            logger.debug("[DependencySources] 读取 jar 失败 %s: %s", path, e)
    return result


def index_source_roots(source_roots: list[MaterializedSourceRoot]) -> dict:
    """索引源码根目录（占位，供后续扩展）。"""
    return {"roots": [r.path for r in source_roots], "count": len(source_roots)}


def resolve_symbol_generic_fallback(project_root: str, symbol: str, limit: int = 15) -> list[CodeLocation]:
    """
    非 AST 强语言兜底：Go/JS/TS/Rust 等用正则约束检索 + 片段验证。
    在 repo 源码中搜索符号定义（func/const/class/function 等模式）。
    """
    if not symbol or not project_root:
        return []
    base = Path(project_root)
    if not base.exists() or not base.is_dir():
        return []
    simple_name = symbol.split(".")[-1].split("/")[-1] if symbol else symbol
    if not simple_name or len(simple_name) < 2:
        return []
    # 多语言定义模式：(扩展名列表, 正则)
    lang_patterns: list[tuple[list[str], str]] = [
        (["go"], rf"\b(?:func|const|var)\s+{re.escape(simple_name)}\b"),
        (["js", "ts", "jsx", "tsx"], rf"\b(?:function|const|let|var|class)\s+{re.escape(simple_name)}\b"),
        (["rs"], rf"\b(?:fn|const|struct|enum)\s+{re.escape(simple_name)}\b"),
    ]
    result: list[CodeLocation] = []
    for exts, def_pat in lang_patterns:
        regex = re.compile(def_pat, re.MULTILINE)
        for ext in exts:
            for p in base.rglob(f"*.{ext}"):
                if len(result) >= limit:
                    return result
                if not p.is_file():
                    continue
                try:
                    text = p.read_text(encoding="utf-8", errors="replace")
                except OSError:
                    continue
                for m in regex.finditer(text):
                    line_num = text[: m.start()].count("\n") + 1
                    line_start = text.rfind("\n", 0, m.start()) + 1
                    line_end = text.find("\n", line_start)
                    if line_end < 0:
                        line_end = len(text)
                    preview = text[line_start:line_end].strip()[:120]
                    try:
                        rel = str(p.relative_to(base))
                    except ValueError:
                        rel = str(p)
                    result.append(
                        CodeLocation(
                            file_path=rel,
                            line=line_num,
                            character=m.start() - line_start,
                            preview=preview,
                        )
                    )
                    if len(result) >= limit:
                        return result
    return result


def _get_venv_python(project_root: str) -> str | None:
    """获取项目 venv 的 python 路径。优先 venv，其次 .venv。"""
    base = Path(project_root)
    for rel in ("venv/bin/python", ".venv/bin/python", "venv/Scripts/python.exe", ".venv/Scripts/python.exe"):
        p = base / rel
        if p.exists():
            return str(p)
    return None


def fetch_python_package_paths(project_root: str) -> list[tuple[str, str, str]]:
    """
    通过 importlib.metadata 获取已安装包的版本与安装路径。
    优先使用项目 venv；无 venv 时使用当前解释器（需显式配置允许）。
    返回 [(name, version, location), ...]
    """
    from root_seeker.services.external_deps import parse_external

    deps = parse_external(project_root)
    if deps.ecosystem != "python":
        return []
    names = [d.name or (d.artifact_id if d.artifact_id else "") for d in deps.direct_dependencies if d.name or d.artifact_id]
    if not names:
        return []

    python = _get_venv_python(project_root) or "python3"
    script = """
import importlib.metadata
import sys
packages = sys.argv[1:]
for pkg in packages:
    try:
        dist = importlib.metadata.distribution(pkg)
        print(f"{dist.metadata['Name']}|||{dist.version}|||{dist.locate_file('')}")
    except Exception:
        pass
"""
    try:
        p = subprocess.run(
            [python, "-c", script] + names,
            capture_output=True,
            text=True,
            timeout=10,
            cwd=project_root,
        )
        result: list[tuple[str, str, str]] = []
        for line in (p.stdout or "").strip().splitlines():
            if "|||" in line:
                parts = line.split("|||", 2)
                if len(parts) >= 3:
                    result.append((parts[0], parts[1], parts[2]))
        return result
    except (subprocess.TimeoutExpired, FileNotFoundError) as e:
        logger.debug("[DependencySources] 获取 Python 包路径失败: %s", e)
        return []


def resolve_symbol_in_python_sources(
    symbol: str,
    package_paths: list[tuple[str, str, str]],
    limit: int = 15,
) -> list[CodeLocation]:
    """在 site-packages 源码中搜索符号（def/class 名）。"""
    if not symbol or not package_paths:
        return []
    simple_name = symbol.split(".")[-1] if "." in symbol else symbol
    pattern = re.compile(rf"\b(?:def|class)\s+{re.escape(simple_name)}\b", re.MULTILINE)
    result: list[CodeLocation] = []
    for _name, _version, loc in package_paths:
        if len(result) >= limit:
            break
        root = Path(loc)
        if not root.exists():
            continue
        for py in root.rglob("*.py"):
            if len(result) >= limit:
                break
            try:
                text = py.read_text(encoding="utf-8", errors="replace")
            except OSError:
                continue
            for m in pattern.finditer(text):
                line_num = text[: m.start()].count("\n") + 1
                line_start = text.rfind("\n", 0, m.start()) + 1
                line_end = text.find("\n", line_start)
                if line_end < 0:
                    line_end = len(text)
                preview = text[line_start:line_end].strip()[:120]
                try:
                    rel = str(py.relative_to(root))
                except ValueError:
                    rel = str(py)
                result.append(
                    CodeLocation(
                        file_path=f"{root}/{rel}",
                        line=line_num,
                        character=m.start() - line_start,
                        preview=preview,
                    )
                )
            if len(result) >= limit:
                break
    return result
