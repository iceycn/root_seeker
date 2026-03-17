"""外部依赖识别服务：解析 Maven/Gradle/Python 构建文件，形成结构化依赖画像。"""

from __future__ import annotations

import re
import xml.etree.ElementTree as ET
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

logger = __import__("logging").getLogger(__name__)


@dataclass
class DeclaredDep:
    """声明的依赖项。"""

    group_id: str | None = None  # Maven/Gradle
    artifact_id: str | None = None
    version: str | None = None
    scope: str | None = None  # compile, runtime, test
    name: str | None = None  # Python: package name
    extras: str | None = None  # Python: [dev,test]
    version_spec: str | None = None  # Python: ==, >=, ~=


@dataclass
class DeclaredVariable:
    """声明中的变量（如 ${spring.version}）。"""

    name: str
    raw: str
    resolved: bool = False


@dataclass
class BinaryDep:
    """二进制依赖（jar/whl/so/dylib 等）。"""

    path: str
    kind: str  # jar | whl | so | dylib | dll
    size_bytes: int = 0


@dataclass
class DeclaredDeps:
    """解析后的声明依赖。"""

    ecosystem: str  # maven | gradle | python
    direct_dependencies: list[DeclaredDep] = field(default_factory=list)
    declared_variables: list[DeclaredVariable] = field(default_factory=list)
    risk_flags: list[str] = field(default_factory=list)
    manifest_path: str | None = None


@dataclass
class ResolvedDep:
    """解析后的依赖（来自 mvn dependency:tree / gradle dependencies / pip freeze）。"""

    group_id: str | None = None
    artifact_id: str | None = None
    version: str | None = None
    scope: str | None = None
    name: str | None = None  # Python
    depth: int = 0  # 传递深度


@dataclass
class DriftItem:
    """声明与解析的漂移项。"""

    kind: str  # declared_not_resolved | resolved_not_declared | version_mismatch
    declared: DeclaredDep | None = None
    resolved: ResolvedDep | None = None
    message: str = ""


@dataclass
class DriftReport:
    """声明 vs 解析的漂移报告。"""

    declared_not_resolved: list[DeclaredDep] = field(default_factory=list)
    resolved_not_declared: list[ResolvedDep] = field(default_factory=list)
    version_mismatches: list[DriftItem] = field(default_factory=list)


def _parse_maven_pom(pom_path: Path) -> DeclaredDeps:
    """解析 pom.xml。"""
    result = DeclaredDeps(ecosystem="maven")
    result.manifest_path = str(pom_path)
    try:
        tree = ET.parse(pom_path)
        root = tree.getroot()
        ns = {"m": "http://maven.apache.org/POM/4.0.0"}
        if root.tag.startswith("{"):
            ns["m"] = root.tag[1 : root.tag.index("}")]
        else:
            ns["m"] = ""

        def _find(tag: str) -> str | None:
            for e in root.iter():
                if tag in e.tag:
                    return (e.text or "").strip()
            return None

        def _local_tag(tag: str) -> str:
            return tag.split("}")[-1] if "}" in tag else tag

        for dep in root.iter():
            if _local_tag(dep.tag) != "dependency":
                continue
            g = None
            a = None
            v = None
            s = "compile"
            for c in dep:
                lt = _local_tag(c.tag)
                if lt == "groupId":
                    g = (c.text or "").strip()
                elif lt == "artifactId":
                    a = (c.text or "").strip()
                elif lt == "version":
                    v = (c.text or "").strip()
                elif lt == "scope":
                    s = (c.text or "").strip() or "compile"
            if g and a:
                if v and "${" in v:
                    result.declared_variables.append(
                        DeclaredVariable(name=v[2:-1], raw=v, resolved=False)
                    )
                    result.risk_flags.append("version_variable")
                result.direct_dependencies.append(
                    DeclaredDep(group_id=g, artifact_id=a, version=v, scope=s)
                )
    except ET.ParseError as e:
        logger.warning("[external_deps] pom.xml 解析失败: %s", e)
        result.risk_flags.append("parse_error")
    except Exception as e:
        logger.warning("[external_deps] pom.xml 读取失败: %s", e)
        result.risk_flags.append("read_error")
    return result


def _parse_gradle_build(build_path: Path) -> DeclaredDeps:
    """解析 build.gradle 或 build.gradle.kts（简化正则）。"""
    result = DeclaredDeps(ecosystem="gradle")
    result.manifest_path = str(build_path)
    try:
        content = build_path.read_text(encoding="utf-8", errors="replace")
        # implementation("group:artifact:version") 或 implementation("group:artifact:version") { ... }
        # compile("group:artifact:version")
        pattern = re.compile(
            r'(?:implementation|api|compile|runtime|testImplementation|testRuntime)\s*\(\s*["\']([^"\']+)["\']\s*\)',
            re.MULTILINE,
        )
        for m in pattern.finditer(content):
            coord = m.group(1)
            parts = coord.split(":")
            if len(parts) >= 2:
                g = parts[0]
                a = parts[1]
                v = parts[2] if len(parts) >= 3 else None
                if v and "${" in v:
                    result.declared_variables.append(
                        DeclaredVariable(name=v[2:-1].split(".")[0], raw=v, resolved=False)
                    )
                    result.risk_flags.append("version_variable")
                result.direct_dependencies.append(
                    DeclaredDep(group_id=g, artifact_id=a, version=v)
                )
    except Exception as e:
        logger.warning("[external_deps] gradle 解析失败: %s", e)
        result.risk_flags.append("parse_error")
    return result


def _parse_requirements_txt(req_path: Path) -> DeclaredDeps:
    """解析 requirements.txt。"""
    result = DeclaredDeps(ecosystem="python")
    result.manifest_path = str(req_path)
    try:
        for line in req_path.read_text(encoding="utf-8", errors="replace").splitlines():
            line = line.strip()
            if not line or line.startswith("#") or line.startswith("-"):
                continue
            # 简单解析：package==1.0.0 或 package>=1.0
            m = re.match(r"^([a-zA-Z0-9_-]+)\s*([=~<>!]+)\s*(.+)$", line)
            if m:
                name, op, ver = m.groups()
                result.direct_dependencies.append(
                    DeclaredDep(name=name, version_spec=f"{op}{ver}", version=ver)
                )
                if op in ("~=", ">=") or ".*" in ver:
                    result.risk_flags.append("dynamic_range")
            else:
                m2 = re.match(r"^([a-zA-Z0-9_-]+)\s*$", line)
                if m2:
                    result.direct_dependencies.append(
                        DeclaredDep(name=m2.group(1), version_spec=None)
                    )
    except Exception as e:
        logger.warning("[external_deps] requirements.txt 解析失败: %s", e)
        result.risk_flags.append("parse_error")
    return result


def _parse_pyproject_toml(pyproject_path: Path) -> DeclaredDeps:
    """解析 pyproject.toml。"""
    result = DeclaredDeps(ecosystem="python")
    result.manifest_path = str(pyproject_path)
    try:
        raw = pyproject_path.read_text(encoding="utf-8", errors="replace")
        try:
            import tomllib
        except ImportError:
            import tomli as tomllib
        data = tomllib.loads(raw)
        deps = data.get("project", {}).get("dependencies", [])
        if isinstance(deps, list):
            for d in deps:
                if isinstance(d, str):
                    m = re.match(r"^([a-zA-Z0-9_-]+)\s*([=~<>!]+)\s*(.+)$", d)
                    if m:
                        name, op, ver = m.groups()
                        result.direct_dependencies.append(
                            DeclaredDep(name=name, version_spec=f"{op}{ver}", version=ver)
                        )
                    else:
                        m2 = re.match(r"^([a-zA-Z0-9_-]+)\s*$", d)
                        if m2:
                            result.direct_dependencies.append(DeclaredDep(name=m2.group(1)))
    except ImportError:
        result.risk_flags.append("toml_parse_unavailable")
    except Exception as e:
        logger.warning("[external_deps] pyproject.toml 解析失败: %s", e)
        result.risk_flags.append("parse_error")
    return result


def parse_maven_pom(project_root: str, pom_path: str | None = None) -> DeclaredDeps:
    """解析 Maven 项目。"""
    base = Path(project_root)
    if pom_path:
        path = base / pom_path.lstrip("/")
    else:
        path = base / "pom.xml"
    if not path.exists():
        return DeclaredDeps(ecosystem="maven", risk_flags=["manifest_not_found"])
    return _parse_maven_pom(path)


def parse_gradle_build(project_root: str, build_file: str | None = None) -> DeclaredDeps:
    """解析 Gradle 项目。"""
    base = Path(project_root)
    for name in (build_file,) if build_file else ("build.gradle.kts", "build.gradle"):
        if name:
            path = base / name.lstrip("/")
            if path.exists():
                return _parse_gradle_build(path)
    return DeclaredDeps(ecosystem="gradle", risk_flags=["manifest_not_found"])


def parse_python_manifest(project_root: str) -> DeclaredDeps:
    """解析 Python 项目（pyproject.toml 优先，否则 requirements.txt）。"""
    base = Path(project_root)
    pyproject = base / "pyproject.toml"
    if pyproject.exists():
        return _parse_pyproject_toml(pyproject)
    req = base / "requirements.txt"
    if req.exists():
        return _parse_requirements_txt(req)
    return DeclaredDeps(ecosystem="python", risk_flags=["manifest_not_found"])


def parse_external(project_root: str, manifest_file: str | None = None) -> DeclaredDeps:
    """自动检测并解析构建文件。"""
    base = Path(project_root)
    if not base.exists():
        return DeclaredDeps(ecosystem="unknown", risk_flags=["project_root_not_found"])

    if manifest_file:
        path = base / manifest_file.lstrip("/")
        if path.exists():
            name = path.name.lower()
            if name == "pom.xml":
                return _parse_maven_pom(path)
            if name in ("build.gradle", "build.gradle.kts"):
                return _parse_gradle_build(path)
            if name == "requirements.txt":
                return _parse_requirements_txt(path)
            if name == "pyproject.toml":
                return _parse_pyproject_toml(path)

    if (base / "pom.xml").exists():
        return parse_maven_pom(project_root)
    if (base / "build.gradle.kts").exists():
        return parse_gradle_build(project_root, "build.gradle.kts")
    if (base / "build.gradle").exists():
        return parse_gradle_build(project_root, "build.gradle")
    if (base / "pyproject.toml").exists():
        return parse_python_manifest(project_root)
    if (base / "requirements.txt").exists():
        return parse_python_manifest(project_root)

    return DeclaredDeps(ecosystem="unknown", risk_flags=["no_manifest_found"])


def scan_binaries(
    project_root: str,
    patterns: list[str] | None = None,
    max_per_kind: int = 50,
) -> list[BinaryDep]:
    """扫描 project_root 下的二进制依赖（jar/whl/so/dylib 等）作为额外证据。"""
    patterns = patterns or ["*.jar", "*.whl", "*.so", "*.dylib"]
    base = Path(project_root)
    if not base.exists():
        return []
    kind_map = {
        "jar": ".jar",
        "whl": ".whl",
        "so": ".so",
        "dylib": ".dylib",
        "dll": ".dll",
    }
    suffix_to_kind = {v: k for k, v in kind_map.items()}
    result: list[BinaryDep] = []
    counts: dict[str, int] = {}
    for pat in patterns:
        for p in base.rglob(pat):
            if not p.is_file():
                continue
            kind = suffix_to_kind.get(p.suffix.lower(), p.suffix.lstrip(".") or "unknown")
            if counts.get(kind, 0) >= max_per_kind:
                continue
            counts[kind] = counts.get(kind, 0) + 1
            try:
                size = p.stat().st_size
            except OSError:
                size = 0
            result.append(
                BinaryDep(path=str(p.relative_to(base)), kind=kind, size_bytes=size)
            )
    return result


def _dep_to_key(d: DeclaredDep | ResolvedDep) -> str:
    """生成依赖唯一键。"""
    if getattr(d, "group_id", None) and getattr(d, "artifact_id", None):
        return f"{d.group_id}:{d.artifact_id}"
    if getattr(d, "name", None):
        return (d.name or "").lower()
    return ""


def diff_declared_vs_resolved(
    declared: DeclaredDeps | dict,
    resolved: list[ResolvedDep] | list[dict],
) -> DriftReport:
    """对比声明与解析的依赖，输出漂移项。"""
    report = DriftReport()
    if isinstance(declared, dict):
        deps = declared.get("direct_dependencies", [])
    else:
        deps = declared.direct_dependencies

    resolved_map: dict[str, ResolvedDep] = {}
    for r in resolved or []:
        if isinstance(r, dict):
            r = ResolvedDep(
                group_id=r.get("group_id"),
                artifact_id=r.get("artifact_id"),
                version=r.get("version"),
                name=r.get("name"),
            )
        k = _dep_to_key(r)
        if k:
            resolved_map[k] = r

    declared_set: set[str] = set()
    for d in deps:
        if isinstance(d, dict):
            d = DeclaredDep(
                group_id=d.get("group_id"),
                artifact_id=d.get("artifact_id"),
                version=d.get("version"),
                name=d.get("name"),
            )
        k = _dep_to_key(d)
        declared_set.add(k)
        if k and k not in resolved_map:
            report.declared_not_resolved.append(d)
        elif k and k in resolved_map:
            rv = resolved_map[k].version
            dv = d.version
            if dv and rv and dv != rv and "${" not in (dv or ""):
                report.version_mismatches.append(
                    DriftItem(
                        kind="version_mismatch",
                        declared=d,
                        resolved=resolved_map[k],
                        message=f"声明 {dv} vs 解析 {rv}",
                    )
                )

    for k, r in resolved_map.items():
        if k not in declared_set:
            report.resolved_not_declared.append(r)

    return report


def _as_dict(obj: Any) -> Any:
    """将 dataclass 转为可 JSON 序列化的 dict。"""
    from dataclasses import asdict, is_dataclass
    if is_dataclass(obj) and not isinstance(obj, type):
        return asdict(obj)
    if isinstance(obj, list):
        return [_as_dict(x) for x in obj]
    if isinstance(obj, dict):
        return {k: _as_dict(v) for k, v in obj.items()}
    return obj
