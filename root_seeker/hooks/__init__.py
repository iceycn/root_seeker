"""
Hook 体系：分析生命周期中注入自定义脚本。

支持 Hook 类型：
- AnalysisStart：分析开始
- AnalysisComplete：分析结束
- PreToolUse：工具调用前（可取消）
- PostToolUse：工具调用后

目录：~/.rootseek/hooks/、config.hooks.dirs、项目 .rootseek/hooks/
脚本：Unix 可执行文件（无扩展名）或 PreToolUse.ps1（Windows）
"""

from root_seeker.hooks.types import (
    HookOutput,
    PreToolUseData,
    PostToolUseData,
    AnalysisStartData,
    AnalysisCompleteData,
)
from root_seeker.hooks.hub import HookHub

__all__ = [
    "HookHub",
    "HookOutput",
    "PreToolUseData",
    "PostToolUseData",
    "AnalysisStartData",
    "AnalysisCompleteData",
]
