"""
AI 提示词构建器。

- AIPromptContext：强类型上下文，承载 service_name、tools_summary、index_preview 等
- AIPromptBuilder：按 section 组件化构建，postProcess 清理空行
"""

from __future__ import annotations

import re
from dataclasses import dataclass


@dataclass
class AIPromptContext:
    """AI 提示词上下文。"""

    service_name: str = ""
    query_key: str = ""
    analysis_id: str = ""
    error_log: str = ""
    error_log_preview: str = ""
    tools_summary: str = ""
    index_preview: str = ""
    correlation_preview: str = ""
    discovered_hints: str = ""
    # 下一轮 / 证据收集
    previous_summary: str = ""
    previous_hypotheses: str = ""
    evidence_needs: str = ""
    tool_plan_hint: str = ""
    # 决策 / Synthesize
    round_num: int = 1
    max_rounds: int = 20
    report_summary: str = ""
    hypotheses: str = ""
    suggestions: str = ""
    tool_results: str = ""
    tool_results_preview: str = ""
    # 工具修正
    tool_name: str = ""
    error_code: str = ""
    error_msg: str = ""
    args: str = ""
    progressive_hint: str = ""
    # focus chain
    focus_chain: str = ""


def _post_process(prompt: str) -> str:
    """合并连续空行、去除空 section。"""
    if not prompt or not prompt.strip():
        return ""
    # 合并连续空行为最多两个换行
    s = re.sub(r"\n\s*\n\s*\n+", "\n\n", prompt).strip()
    # 去除空 section：块仅为 "标签：" 或 "标签:" 且无实质内容
    blocks = re.split(r"\n\s*\n", s)
    kept = []
    for b in blocks:
        t = b.strip()
        if not t:
            continue
        # 跳过仅含 "xxx：" 或 "xxx:" 且无其他内容的块
        if re.match(r"^[^\n]*[：:]\s*$", t) and len(t) < 80:
            continue
        kept.append(b.strip())
    return "\n\n".join(kept).strip()


class AIPromptBuilder:
    """组件化提示词构建器。"""

    def __init__(self, template: str, context: AIPromptContext):
        self._template = template
        self._context = context

    def build(self) -> str:
        """解析模板占位符（使用 .format 兼容 {{}} 转义）并 postProcess。"""
        kwargs = {k: (v or "") for k, v in self._context.__dict__.items()}
        try:
            result = self._template.format(**kwargs)
        except KeyError:
            result = self._template
            for k, v in kwargs.items():
                result = result.replace("{" + k + "}", str(v))
        return _post_process(result)


def build_plan_user_prompt(ctx: AIPromptContext) -> str:
    """构建 Plan 阶段 user prompt。"""
    from root_seeker import prompts

    return AIPromptBuilder(prompts.AI_ORCHESTRATOR_PLAN_USER, ctx).build()


def build_plan_next_round_user_prompt(ctx: AIPromptContext) -> str:
    """构建下一轮 Plan 的 user prompt。"""
    from root_seeker import prompts

    return AIPromptBuilder(prompts.AI_ORCHESTRATOR_PLAN_NEXT_ROUND_USER, ctx).build()


def build_synthesize_user_prompt(ctx: AIPromptContext) -> str:
    """构建 Synthesize 阶段 user prompt。"""
    from root_seeker import prompts

    return AIPromptBuilder(prompts.AI_ORCHESTRATOR_SYNTHESIZE_USER, ctx).build()


def build_next_round_decision_user_prompt(ctx: AIPromptContext) -> str:
    """构建下一轮决策 user prompt。"""
    from root_seeker import prompts

    return AIPromptBuilder(prompts.AI_ORCHESTRATOR_NEXT_ROUND_USER, ctx).build()


def build_fix_args_user_prompt(ctx: AIPromptContext) -> str:
    """构建工具参数修正 user prompt。"""
    from root_seeker import prompts

    return AIPromptBuilder(prompts.AI_ORCHESTRATOR_FIX_ARGS_USER, ctx).build()


# 按 section 拆分
def get_objective_section() -> str:
    """Plan 阶段目标 section。"""
    return "你是错误分析工具编排器，负责规划根因分析的执行步骤。Plan 是流程核心，由你决定整个分析路径。给定错误信息与可用工具列表，输出 JSON 格式的「工具调用计划」。"


def get_rules_section() -> str:
    """Plan 阶段规则 section。"""
    return """【核心原则】AI 驱动，证据由 AI 自主收集；每轮计划完整执行。
- 优先路径 A：index.get_status/correlation.get_info → code.search/evidence.context_search → code.read → analysis.synthesize
- 路径 B 兜底：无勘探时用 analysis.run_full
【上下文发现】不确定 repo_id 时先 index.get_status；需 trace 链时先 correlation.get_info；涉及类/方法时先 code.search 再 code.read。"""


def get_tools_section(tools_summary: str) -> str:
    """Plan 阶段工具 section。"""
    return f"可用工具：\n{tools_summary}" if tools_summary else ""


def build_plan_system_from_components() -> str:
    """从组件构建 Plan system prompt（便于扩展）。"""
    from root_seeker import prompts

    # 当前仍使用完整模板，组件可用于未来拆分
    return prompts.AI_ORCHESTRATOR_PLAN_SYSTEM


# focus chain：任务进度清单（参考 Cline 的 focus chain / checklist）
def build_focus_chain(round_num: int, max_rounds: int, completed_steps: list[str]) -> str:
    """生成任务进度清单（checklist），供 Plan 参考。含「追溯上游链路」步骤，当发现数据缺失时引导模型进入该步骤。"""
    steps = ["获取上下文", "定位代码", "收集证据", "分析根因", "追溯上游链路"]
    done = completed_steps[:]
    lines = [f"轮次: {round_num}/{max_rounds}"]
    for i, s in enumerate(steps):
        mark = "✓" if s in done else "○"
        lines.append(f"  {mark} {s}")
    return "\n".join(lines)
