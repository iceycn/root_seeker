"""MCP 安全命令执行工具：cmd.run_build_analysis。仅白名单映射，禁止任意 Shell 注入。"""

from __future__ import annotations

import asyncio
import json
import re
import shutil
from pathlib import Path
from typing import Any, Dict

from root_seeker.mcp.protocol import ErrorCode, ToolResult, ToolSchema
from root_seeker.mcp.tools.base import BaseTool
from root_seeker.services.router import ServiceRouter

# 白名单：tool + command_type -> argv（列表参数，禁止 shell=True）
_CMD_WHITELIST: dict[tuple[str, str], list[str]] = {
    ("maven", "dependency_tree"): ["mvn", "dependency:tree", "-DoutputType=text"],
    ("gradle", "dependencies"): ["./gradlew", "dependencies", "--configuration", "compileClasspath"],
    ("gradle", "dependencies_runtime"): ["./gradlew", "dependencies", "--configuration", "runtimeClasspath"],
    ("python", "pip_freeze"): ["pip", "freeze"],
}

# 输出截断上限
RAW_OUTPUT_MAX_CHARS = 8000


def _parse_maven_tree_output(text: str) -> list[dict]:
    """解析 mvn dependency:tree 输出为结构化列表。"""
    result: list[dict] = []
    for line in text.splitlines():
        line = line.strip()
        if not line or line.startswith("["):
            continue
        # 格式: groupId:artifactId:packaging:version:scope 或带缩进
        m = re.match(r"^[\s\-+\\|]*([a-zA-Z0-9_.-]+):([a-zA-Z0-9_.-]+):([a-zA-Z0-9_.-]*):([a-zA-Z0-9_.-]+):([a-zA-Z]*)", line)
        if m:
            g, a, _pkg, v, s = m.groups()
            result.append({
                "group_id": g,
                "artifact_id": a,
                "version": v,
                "scope": s or "compile",
            })
    return result


def _parse_gradle_output(text: str) -> list[dict]:
    """解析 gradle dependencies 输出为结构化列表。"""
    result: list[dict] = []
    for line in text.splitlines():
        line = line.strip()
        if not line or line.startswith("(") or "---" in line:
            continue
        # 格式: group:artifact:version 或带 +--- \---
        m = re.search(r"([a-zA-Z0-9_.-]+):([a-zA-Z0-9_.-]+):([a-zA-Z0-9_.-]+)", line)
        if m:
            g, a, v = m.groups()
            result.append({"group_id": g, "artifact_id": a, "version": v})
    return result


def _parse_pip_freeze(text: str) -> list[dict]:
    """解析 pip freeze 输出。"""
    result: list[dict] = []
    for line in text.splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        m = re.match(r"^([a-zA-Z0-9_-]+)==(.+)$", line)
        if m:
            result.append({"name": m.group(1), "version": m.group(2)})
    return result


class CmdRunBuildAnalysisTool(BaseTool):
    """cmd.run_build_analysis：安全执行依赖分析命令（mvn/gradle/pip）。"""

    def __init__(self, router: ServiceRouter, timeout_seconds: int = 60):
        self._router = router
        self._timeout = timeout_seconds

    @property
    def name(self) -> str:
        return "cmd.run_build_analysis"

    @property
    def schema(self) -> ToolSchema:
        return ToolSchema(
            name=self.name,
            description="在 project_root 下安全执行依赖分析命令（mvn dependency:tree / gradle dependencies / pip freeze）。仅白名单映射，禁止任意命令注入。未安装构建工具时返回 DEPENDENCY_UNAVAILABLE。",
            inputSchema={
                "type": "object",
                "properties": {
                    "project_root": {"type": "string", "description": "项目根目录"},
                    "repo_id": {"type": "string", "description": "可选，与 project_root 二选一"},
                    "tool": {"type": "string", "enum": ["maven", "gradle", "python"], "description": "构建工具"},
                    "command_type": {
                        "type": "string",
                        "enum": ["dependency_tree", "dependencies", "dependencies_runtime", "pip_freeze"],
                        "description": "maven: dependency_tree; gradle: dependencies; python: pip_freeze",
                    },
                },
                "required": ["tool", "command_type"],
            },
        )

    def _resolve_project_root(self, args: Dict[str, Any], context: Dict[str, Any] | None) -> str | None:
        project_root = args.get("project_root")
        if project_root and isinstance(project_root, str):
            return project_root
        repo_id = args.get("repo_id") or (context or {}).get("service_name")
        if repo_id:
            candidates = self._router.route(str(repo_id))
            if candidates:
                return candidates[0].local_dir
        return None

    async def run(self, args: Dict[str, Any], context: Dict[str, Any] | None = None) -> ToolResult:
        project_root = self._resolve_project_root(args, context)
        if not project_root:
            return ToolResult.error(
                "缺少 project_root 或 repo_id",
                error_code=ErrorCode.INVALID_PARAMS,
            )
        base = Path(project_root)
        if not base.exists():
            return ToolResult.error(f"project_root 不存在: {project_root}", error_code=ErrorCode.INVALID_PARAMS)

        tool = args.get("tool")
        command_type = args.get("command_type")
        if not tool or not command_type:
            return ToolResult.error("缺少 tool 或 command_type", error_code=ErrorCode.INVALID_PARAMS)

        key = (str(tool), str(command_type))
        if key not in _CMD_WHITELIST:
            return ToolResult.error(
                f"不允许的 command_type: {tool}/{command_type}",
                error_code=ErrorCode.INVALID_PARAMS,
            )
        argv = list(_CMD_WHITELIST[key])

        # Gradle: 若无 gradlew 则尝试 gradle
        if tool == "gradle" and argv[0] == "./gradlew":
            gradlew = base / "gradlew"
            if not gradlew.exists():
                gradle_path = shutil.which("gradle")
                if gradle_path:
                    argv = ["gradle", "dependencies", "--configuration", "compileClasspath"]
                else:
                    return ToolResult.error(
                        "未找到 gradlew 或 gradle 命令",
                        error_code=ErrorCode.DEPENDENCY_UNAVAILABLE,
                    )
            else:
                argv[0] = str(gradlew)

        # Python: 优先使用项目 venv 的 pip
        if tool == "python":
            venv_pip = base / "venv" / "bin" / "pip"
            if venv_pip.exists():
                argv = [str(venv_pip), "freeze"]
            elif (base / ".venv" / "bin" / "pip").exists():
                argv = [str(base / ".venv" / "bin" / "pip"), "freeze"]
            elif not shutil.which("pip"):
                return ToolResult.error(
                    "未找到 pip 命令",
                    error_code=ErrorCode.DEPENDENCY_UNAVAILABLE,
                )

        # Maven: 检查 mvn
        if tool == "maven" and not shutil.which("mvn"):
            return ToolResult.error(
                "未找到 mvn 命令",
                error_code=ErrorCode.DEPENDENCY_UNAVAILABLE,
            )

        try:
            proc = await asyncio.create_subprocess_exec(
                *argv,
                cwd=str(base),
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            stdout, stderr = await asyncio.wait_for(
                proc.communicate(),
                timeout=self._timeout,
            )
            raw = (stdout or b"").decode("utf-8", errors="replace")
            err_text = (stderr or b"").decode("utf-8", errors="replace")
            if proc.returncode != 0:
                return ToolResult.error(
                    f"命令执行失败 (exit={proc.returncode}): {err_text[:500]}",
                    error_code=ErrorCode.INTERNAL_ERROR,
                )

            # 解析输出
            if tool == "maven":
                resolved = _parse_maven_tree_output(raw)
            elif tool == "gradle":
                resolved = _parse_gradle_output(raw)
            else:
                resolved = _parse_pip_freeze(raw)

            is_truncated = len(raw) > RAW_OUTPUT_MAX_CHARS
            excerpt = raw[:RAW_OUTPUT_MAX_CHARS] + ("..." if is_truncated else "")

            out = {
                "resolved_dependencies": resolved,
                "raw_output_excerpt": excerpt,
                "is_truncated": is_truncated,
            }
            return ToolResult.text(json.dumps(out, ensure_ascii=False))
        except asyncio.TimeoutError:
            return ToolResult.error(
                f"命令执行超时 ({self._timeout}s)",
                error_code=ErrorCode.TOOL_TIMEOUT,
            )
        except FileNotFoundError as e:
            return ToolResult.error(
                f"未找到可执行文件: {e}",
                error_code=ErrorCode.DEPENDENCY_UNAVAILABLE,
            )
        except Exception as e:
            return ToolResult.error(
                f"cmd.run_build_analysis 执行失败: {e}",
                error_code=ErrorCode.INTERNAL_ERROR,
            )
