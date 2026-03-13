"""
Hook 脚本执行器：JSON stdin → 子进程 → 解析 JSON stdout。
"""

from __future__ import annotations

import asyncio
import json
import logging
import platform
import subprocess
from pathlib import Path

from root_seeker.hooks.types import HookOutput

logger = logging.getLogger(__name__)

DEFAULT_TIMEOUT_SECONDS = 30
MAX_OUTPUT_BYTES = 1024 * 1024  # 1MB
# contextModification 超长时截断
MAX_CONTEXT_MODIFICATION_BYTES = 50_000


def _run_hook_sync(script_path: Path, input_json: str, timeout: int) -> tuple[int, str, str]:
    """同步执行 hook，返回 (exit_code, stdout, stderr)。"""
    if platform.system() == "Windows":
        cmd = [
            "powershell",
            "-NoProfile",
            "-NonInteractive",
            "-ExecutionPolicy",
            "Bypass",
            "-File",
            str(script_path),
        ]
        proc = subprocess.run(
            cmd,
            input=input_json.encode("utf-8"),
            capture_output=True,
            timeout=timeout,
            cwd=script_path.parent,
        )
    else:
        # Unix：直接执行脚本（需可执行权限，支持 shebang）
        proc = subprocess.run(
            [str(script_path)],
            input=input_json.encode("utf-8"),
            capture_output=True,
            timeout=timeout,
            cwd=script_path.parent,
        )
    stdout = proc.stdout.decode("utf-8", errors="replace") if proc.stdout else ""
    stderr = proc.stderr.decode("utf-8", errors="replace") if proc.stderr else ""
    return proc.returncode or 0, stdout[:MAX_OUTPUT_BYTES], stderr[:MAX_OUTPUT_BYTES]


def _validate_and_truncate_context_modification(s: str) -> str:
    """contextModification 超 50KB 时截断。"""
    if not s or len(s) <= MAX_CONTEXT_MODIFICATION_BYTES:
        return s
    return s[:MAX_CONTEXT_MODIFICATION_BYTES] + "\n\n[... context truncated due to size limit ...]"


def _parse_hook_output(stdout: str) -> HookOutput | None:
    """
    从 stdout 解析 JSON 输出。从末尾扫描找最后一个完整 JSON 对象（支持多行）。
    返回 None 表示解析失败。
    """
    def _try_parse(obj: dict) -> HookOutput:
        ctx = str(obj.get("contextModification", obj.get("context_modification", "")) or "")
        ctx = _validate_and_truncate_context_modification(ctx)
        return HookOutput(
            cancel=bool(obj.get("cancel", False)),
            context_modification=ctx,
            error_message=str(obj.get("errorMessage", obj.get("error_message", "")) or ""),
        )

    # 先尝试整段解析
    try:
        obj = json.loads(stdout.strip())
        if isinstance(obj, dict):
            return _try_parse(obj)
    except json.JSONDecodeError:
        pass

    # 从末尾扫描找最后一个完整 JSON 对象（按括号匹配）
    lines = stdout.strip().split("\n")
    brace_count = 0
    start_collecting = False
    json_candidate = ""
    for i in range(len(lines) - 1, -1, -1):
        line = lines[i].rstrip()
        for j in range(len(line) - 1, -1, -1):
            if line[j] == "}":
                brace_count += 1
                start_collecting = True
            elif line[j] == "{":
                brace_count -= 1
        if start_collecting:
            json_candidate = line + ("\n" + json_candidate if json_candidate else "")
        if start_collecting and brace_count == 0:
            break
    if json_candidate.strip():
        first_brace = json_candidate.strip().find("{")
        if first_brace >= 0:
            cleaned = json_candidate.strip()[first_brace:]
            try:
                obj = json.loads(cleaned)
                if isinstance(obj, dict):
                    return _try_parse(obj)
            except json.JSONDecodeError:
                pass

    # 兜底：逐行尝试
    for line in reversed([ln.strip() for ln in stdout.strip().split("\n") if ln.strip()]):
        if line.startswith("{"):
            try:
                obj = json.loads(line)
                if isinstance(obj, dict):
                    return _try_parse(obj)
            except json.JSONDecodeError:
                continue
    return None


async def run_hook(
    script_path: Path,
    input_json: str,
    timeout_seconds: int = DEFAULT_TIMEOUT_SECONDS,
) -> HookOutput:
    """
    执行 hook 脚本：stdin 传入 JSON，解析 stdout 为 HookOutput。
    有效 JSON 优先于 exit code；非零退出但提供有效 JSON 时仍使用 JSON。
    """
    try:
        exit_code, stdout, stderr = await asyncio.to_thread(
            _run_hook_sync, script_path, input_json, timeout_seconds
        )
        if stderr:
            logger.debug("[Hook] %s stderr: %s", script_path.name, stderr[:200])
        parsed = _parse_hook_output(stdout)
        if parsed is not None:
            if exit_code != 0:
                logger.debug(
                    "[Hook] %s 退出码 %d 但提供了有效 JSON，使用 JSON 结果",
                    script_path.name, exit_code,
                )
            return parsed
        if exit_code != 0:
            logger.warning("[Hook] %s 退出码 %d", script_path.name, exit_code)
            return HookOutput(
                cancel=False,
                error_message=f"Hook exited with code {exit_code}",
            )
        return HookOutput()
    except subprocess.TimeoutExpired:
        logger.warning("[Hook] %s 超时 %ds", script_path.name, timeout_seconds)
        return HookOutput(error_message=f"Hook timed out after {timeout_seconds}s")
    except Exception as e:
        logger.warning("[Hook] %s 执行失败: %s", script_path.name, e)
        return HookOutput(error_message=str(e))
