"""
工具错误格式化。

统一错误格式便于 AI 理解，支持结构化 <error> 标签。
参考 Cline 3.72.0 异常处理模式：按错误类型差异化，每种错误给出可操作建议。
"""

from __future__ import annotations

import re

# 不可修正的错误码（建议直接 abort，无需调用错误判断 AI）
UNRECOVERABLE_ERROR_CODES = frozenset({"TOOL_NOT_FOUND", "DEPENDENCY_UNAVAILABLE"})


def format_tool_error(
    error: str,
    *,
    tool_name: str | None = None,
    error_code: str | None = None,
    param_name: str | None = None,
) -> str:
    """结构化错误文案，便于 AI 解析。按 error_code 使用专用格式化（Cline 风格）。

    Args:
        error: 错误信息
        tool_name: 可选，工具名
        error_code: 可选，错误码（INVALID_PARAMS、TOOL_TIMEOUT 等）
        param_name: 可选，缺失/错误的参数名（INVALID_PARAMS 时优先标出）

    Returns:
        格式化后的错误文本，含 <error> 标签
    """
    parts = ["工具执行失败"]
    if tool_name:
        parts.append(f"工具: {tool_name}")
    if error_code:
        parts.append(f"错误码: {error_code}")
    header = "，".join(parts) + "："

    # 按错误类型使用专用 body（Cline 风格：每种错误给出可操作建议）
    body = _build_error_body(error, error_code, param_name)

    return f"{header}\n<error>\n{body}\n</error>"


def _build_error_body(error: str, error_code: str | None, param_name: str | None) -> str:
    """按错误码构建差异化错误正文。"""
    if error_code == "INVALID_PARAMS" and param_name:
        body = format_missing_param_error(param_name)
        if error and error != body:
            body = f"{body}\n原始信息: {error}"
        return body

    if error_code == "TOOL_TIMEOUT":
        return format_tool_timeout_error(error)

    if error_code == "DEPENDENCY_UNAVAILABLE":
        return format_dependency_unavailable_error(error)

    if error_code == "TOOL_NOT_FOUND":
        return format_tool_not_found_error(error)

    return error


def format_missing_param_error(param_name: str) -> str:
    """缺少必填参数（参考 Cline missingToolParameterError）。"""
    return f"缺少必填参数 '{param_name}'。请重试并补全该参数。"


def format_tool_timeout_error(original: str) -> str:
    """超时错误（参考 Cline：给出可操作建议）。"""
    return (
        f"{original}\n\n"
        "建议：可尝试简化参数、缩小检索范围（如减小 depth、limit）或更换工具后重试。"
    )


def format_dependency_unavailable_error(original: str) -> str:
    """依赖不可用（参考 Cline：通常需 abort）。"""
    return f"{original}\n\n建议：依赖不可用时通常无法修正，建议 abort 并回退到直连分析。"


def format_tool_not_found_error(original: str) -> str:
    """工具不存在（参考 Cline：abort）。"""
    return f"{original}\n\n建议：工具不存在，无法修正，请 abort。"


def extract_missing_param_from_error(error: str) -> str | None:
    """从错误信息中解析缺失参数名，供 format_tool_error 使用。

    支持格式：缺少必填参数 X、缺少必填参数: X、缺少必填参数 X 或 Y
    """
    if not error or "缺少" not in error or "参数" not in error:
        return None
    m = re.search(r"缺少必填参数[：:\s]+(.+?)(?:\s*$|。)", error)
    if m:
        return m.group(1).strip()
    m = re.search(r"缺少必填参数\s+([\w_]+(?:\s+或\s+[\w_]+)?)", error)
    if m:
        return m.group(1).strip()
    return None


def format_too_many_mistakes(feedback: str | None = None) -> str:
    """连续失败过多时的提示（参考 Cline tooManyMistakes）。"""
    base = "连续失败次数过多，请检查参数或更换策略。"
    if feedback:
        return f"{base}\n<feedback>\n{feedback}\n</feedback>"
    return base
