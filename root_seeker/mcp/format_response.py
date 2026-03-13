"""
工具错误格式化。

统一错误格式便于 AI 理解，支持结构化 <error> 标签。
"""

from __future__ import annotations


def format_tool_error(
    error: str,
    *,
    tool_name: str | None = None,
    error_code: str | None = None,
) -> str:
    """结构化错误文案，便于 AI 解析。

    Args:
        error: 错误信息
        tool_name: 可选，工具名
        error_code: 可选，错误码（INVALID_PARAMS、TOOL_TIMEOUT 等）

    Returns:
        格式化后的错误文本，含 <error> 标签
    """
    parts = ["工具执行失败"]
    if tool_name:
        parts.append(f"工具: {tool_name}")
    if error_code:
        parts.append(f"错误码: {error_code}")
    header = "，".join(parts) + "："
    return f"{header}\n<error>\n{error}\n</error>"


def format_too_many_mistakes(feedback: str | None = None) -> str:
    """连续失败过多时的提示。"""
    base = "连续失败次数过多，请检查参数或更换策略。"
    if feedback:
        return f"{base}\n<feedback>\n{feedback}\n</feedback>"
    return base


def format_missing_param_error(param_name: str) -> str:
    """缺少必填参数。"""
    return f"缺少必填参数 '{param_name}'，请重试并补全参数。"
