"""
Hook 输入输出类型定义。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


# 支持的 Hook 类型
HOOK_NAMES = ("AnalysisStart", "AnalysisComplete", "PreToolUse", "PostToolUse")


@dataclass
class PreToolUseData:
    """PreToolUse：工具调用前。"""
    tool_name: str
    parameters: dict[str, Any]


@dataclass
class PostToolUseData:
    """PostToolUse：工具调用后。"""
    tool_name: str
    parameters: dict[str, Any]
    result: str
    success: bool
    execution_time_ms: int


@dataclass
class AnalysisStartData:
    """AnalysisStart：分析开始。"""
    task_metadata: dict[str, str] = field(default_factory=dict)


@dataclass
class AnalysisCompleteData:
    """AnalysisComplete：分析结束。"""
    task_metadata: dict[str, str] = field(default_factory=dict)


@dataclass
class HookOutput:
    """Hook 脚本输出。"""
    cancel: bool = False
    context_modification: str = ""
    error_message: str = ""
