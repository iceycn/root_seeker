"""Hook 体系测试：发现、执行、缓存。"""

from __future__ import annotations

import asyncio
import sys
import tempfile
from pathlib import Path

import pytest

from root_seeker.hooks.discovery import (
    HookDiscoveryCache,
    find_hook_in_dir,
    get_all_hooks_dirs,
)
from root_seeker.hooks.executor import run_hook
from root_seeker.hooks.hub import HookHub


def test_get_all_hooks_dirs():
    """get_all_hooks_dirs 返回存在的目录。"""
    with tempfile.TemporaryDirectory() as tmp:
        extra = [tmp]
        dirs = get_all_hooks_dirs(extra_dirs=extra)
        assert any(Path(tmp).resolve() == d.resolve() for d in dirs)


def test_find_hook_in_dir():
    """find_hook_in_dir 在目录中查找脚本。"""
    with tempfile.TemporaryDirectory() as tmp:
        p = Path(tmp)
        # 创建可执行 PreToolUse 脚本
        script = p / "PreToolUse"
        script.write_text("#!/bin/sh\necho '{}'")
        script.chmod(0o755)
        found = find_hook_in_dir("PreToolUse", p)
        assert found == script
        assert find_hook_in_dir("AnalysisStart", p) is None


def test_hook_discovery_cache():
    """HookDiscoveryCache 缓存发现结果。"""
    with tempfile.TemporaryDirectory() as tmp:
        extra = [tmp]
        cache = HookDiscoveryCache(extra_dirs=extra)
        assert cache.has_hook("PreToolUse") is False
        # 创建脚本
        script = Path(tmp) / "PreToolUse"
        script.write_text("#!/bin/sh\necho '{}'")
        script.chmod(0o755)
        cache.invalidate_all()
        paths = cache.get("PreToolUse")
        assert len(paths) == 1
        assert cache.has_hook("PreToolUse") is True


def test_run_hook():
    """run_hook 执行脚本并解析 JSON 输出。"""
    with tempfile.TemporaryDirectory() as tmp:
        script = Path(tmp) / "PreToolUse"
        script.write_text(f"""#!{sys.executable}
import sys, json
sys.stdin.read()  # 消费 stdin
print(json.dumps({{"cancel": False, "contextModification": "test"}}))
""")
        script.chmod(0o755)
        out = asyncio.run(run_hook(script, '{"test": 1}'))
        assert out.cancel is False
        assert "test" in out.context_modification


def test_hook_hub_no_hooks():
    """HookHub 无脚本时返回空输出。"""
    hub = HookHub(enabled=True, hooks_dirs=[])
    out = asyncio.run(hub.execute_pre_tool_use("aid-1", "code.read", {"file_path": "a.java"}))
    assert out.cancel is False
    assert out.context_modification == ""


def test_hook_hub_with_script():
    """HookHub 有脚本时执行并返回结果。"""
    with tempfile.TemporaryDirectory() as tmp:
        script = Path(tmp) / "PreToolUse"
        script.write_text(f"""#!{sys.executable}
import sys, json
sys.stdin.read()
print(json.dumps({{"cancel": True, "errorMessage": "blocked"}}))
""")
        script.chmod(0o755)
        hub = HookHub(enabled=True, hooks_dirs=[tmp])
        out = asyncio.run(hub.execute_pre_tool_use("aid-1", "code.read", {"file_path": "a.java"}))
        assert out.cancel is True
        assert "blocked" in out.error_message


def test_run_hook_valid_json_overrides_exit_code():
    """非零退出但有效 JSON 时仍使用 JSON 结果。"""
    with tempfile.TemporaryDirectory() as tmp:
        script = Path(tmp) / "PreToolUse"
        script.write_text(f"""#!{sys.executable}
import sys, json
sys.stdin.read()
print(json.dumps({{"cancel": True, "errorMessage": "from_json"}}))
sys.exit(1)  # 故意非零退出
""")
        script.chmod(0o755)
        out = asyncio.run(run_hook(script, '{{}}'))
        assert out.cancel is True
        assert "from_json" in out.error_message
