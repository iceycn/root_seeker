"""
Hook 调度中心：发现 + 执行。
"""

from __future__ import annotations

import json
import logging
import time
from typing import Any

from root_seeker.hooks.discovery import HookDiscoveryCache, HookName
from root_seeker.hooks.executor import run_hook
from root_seeker.hooks.types import (
    AnalysisCompleteData,
    AnalysisStartData,
    HookOutput,
    PostToolUseData,
    PreToolUseData,
)

logger = logging.getLogger(__name__)


def _serialize_param_value(v: Any) -> str:
    """parameters 为 map<string,string>，嵌套值需序列化。"""
    if v is None:
        return ""
    if isinstance(v, str):
        return v
    if isinstance(v, (dict, list)):
        return json.dumps(v, ensure_ascii=False)
    return str(v)


def _build_input(
    hook_name: HookName,
    analysis_id: str,
    data: dict[str, Any],
    service_name: str = "",
) -> str:
    """构建 hook 输入 JSON。"""
    payload = {
        "root_seeker_version": "2.0",
        "hook_name": hook_name,
        "timestamp": str(int(time.time() * 1000)),
        "analysis_id": analysis_id,
        "service_name": service_name,
        **data,
    }
    return json.dumps(payload, ensure_ascii=False)


class HookHub:
    """
    Hook 调度中心。负责发现脚本并执行，合并多脚本输出。
    """

    def __init__(self, enabled: bool = True, hooks_dirs: list[str] | None = None):
        self._enabled = enabled
        self._cache = HookDiscoveryCache(extra_dirs=hooks_dirs or [])

    def invalidate_cache(self) -> None:
        """清空发现缓存。"""
        self._cache.invalidate_all()

    def has_hook(self, hook_name: HookName) -> bool:
        """是否存在该 hook 的脚本。"""
        if not self._enabled:
            return False
        return self._cache.has_hook(hook_name)

    async def execute_analysis_start(
        self,
        analysis_id: str,
        service_name: str = "",
        task_metadata: dict[str, str] | None = None,
    ) -> HookOutput:
        """执行 AnalysisStart hook。"""
        return await self._execute(
            "AnalysisStart",
            analysis_id,
            service_name,
            {"task_metadata": task_metadata or {}},
        )

    async def execute_analysis_complete(
        self,
        analysis_id: str,
        service_name: str = "",
        task_metadata: dict[str, str] | None = None,
    ) -> HookOutput:
        """执行 AnalysisComplete hook。"""
        return await self._execute(
            "AnalysisComplete",
            analysis_id,
            service_name,
            {"task_metadata": task_metadata or {}},
        )

    async def execute_pre_tool_use(
        self,
        analysis_id: str,
        tool_name: str,
        parameters: dict[str, Any],
        service_name: str = "",
    ) -> HookOutput:
        """执行 PreToolUse hook。若 cancel=True 则调用方应中止工具调用。"""
        return await self._execute(
            "PreToolUse",
            analysis_id,
            service_name,
            {
                "tool_name": tool_name,
                "parameters": {k: _serialize_param_value(v) for k, v in parameters.items()},
            },
        )

    async def execute_post_tool_use(
        self,
        analysis_id: str,
        tool_name: str,
        parameters: dict[str, Any],
        result: str,
        success: bool,
        execution_time_ms: int,
        service_name: str = "",
    ) -> HookOutput:
        """执行 PostToolUse hook。"""
        return await self._execute(
            "PostToolUse",
            analysis_id,
            service_name,
            {
                "tool_name": tool_name,
                "parameters": {k: _serialize_param_value(v) for k, v in parameters.items()},
                "result": result[:5000],  # 限制长度
                "success": success,
                "execution_time_ms": execution_time_ms,
            },
        )

    async def _execute(
        self,
        hook_name: HookName,
        analysis_id: str,
        service_name: str,
        data: dict[str, Any],
    ) -> HookOutput:
        """执行 hook，合并多脚本输出。"""
        if not self._enabled:
            return HookOutput()
        scripts = self._cache.get(hook_name)
        if not scripts:
            return HookOutput()
        input_json = _build_input(hook_name, analysis_id, data, service_name)
        cancel = False
        context_parts: list[str] = []
        error_parts: list[str] = []
        for script in scripts:
            out = await run_hook(script, input_json)
            if out.cancel:
                cancel = True
            if out.context_modification:
                context_parts.append(out.context_modification)
            if out.error_message:
                error_parts.append(out.error_message)
        return HookOutput(
            cancel=cancel,
            context_modification="\n".join(context_parts).strip(),
            error_message="; ".join(error_parts).strip(),
        )
