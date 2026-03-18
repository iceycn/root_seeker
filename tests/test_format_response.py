"""format_tool_error 测试。"""

from root_seeker.mcp.format_response import (
    UNRECOVERABLE_ERROR_CODES,
    extract_missing_param_from_error,
    format_dependency_unavailable_error,
    format_missing_param_error,
    format_tool_error,
    format_tool_not_found_error,
    format_tool_timeout_error,
    format_too_many_mistakes,
)


def test_format_tool_error():
    out = format_tool_error("连接失败")
    assert "<error>" in out
    assert "连接失败" in out


def test_format_tool_error_with_tool_and_code():
    out = format_tool_error("超时", tool_name="code.search", error_code="TOOL_TIMEOUT")
    assert "code.search" in out
    assert "TOOL_TIMEOUT" in out


def test_format_tool_error_invalid_params_with_param_name():
    """INVALID_PARAMS 且提供 param_name 时，显式标出参数名（Cline 风格）"""
    out = format_tool_error(
        "缺少必填参数 query",
        tool_name="code.search",
        error_code="INVALID_PARAMS",
        param_name="query",
    )
    assert "INVALID_PARAMS" in out
    assert "query" in out
    assert "缺少必填参数" in out
    assert "<error>" in out


def test_extract_missing_param_from_error():
    """从错误信息解析缺失参数名"""
    assert extract_missing_param_from_error("缺少必填参数: target") == "target"
    assert extract_missing_param_from_error("缺少必填参数 query") == "query"
    assert extract_missing_param_from_error("缺少必填参数 service_name 或 error_log") == "service_name 或 error_log"
    assert extract_missing_param_from_error("其他错误") is None
    assert extract_missing_param_from_error("") is None


def test_format_missing_param_error():
    """format_missing_param_error 明确标出参数名"""
    out = format_missing_param_error("file_path")
    assert "file_path" in out
    assert "缺少必填参数" in out


def test_format_tool_timeout_error():
    """TOOL_TIMEOUT 给出可操作建议"""
    out = format_tool_timeout_error("执行超时 60s")
    assert "执行超时" in out
    assert "简化参数" in out or "缩小" in out


def test_format_dependency_unavailable_error():
    """DEPENDENCY_UNAVAILABLE 建议 abort"""
    out = format_dependency_unavailable_error("Zoekt 不可用")
    assert "Zoekt" in out
    assert "abort" in out


def test_format_tool_not_found_error():
    """TOOL_NOT_FOUND 建议 abort"""
    out = format_tool_not_found_error("Tool not found: xxx")
    assert "xxx" in out
    assert "abort" in out


def test_format_tool_error_by_error_code():
    """按 error_code 使用专用格式化"""
    out = format_tool_error("超时", tool_name="code.search", error_code="TOOL_TIMEOUT")
    assert "TOOL_TIMEOUT" in out
    assert "简化" in out or "缩小" in out


def test_unrecoverable_error_codes():
    """不可修正错误码集合"""
    assert "TOOL_NOT_FOUND" in UNRECOVERABLE_ERROR_CODES
    assert "DEPENDENCY_UNAVAILABLE" in UNRECOVERABLE_ERROR_CODES
    assert "INVALID_PARAMS" not in UNRECOVERABLE_ERROR_CODES


def test_format_too_many_mistakes():
    out = format_too_many_mistakes("请检查参数")
    assert "连续失败" in out
    assert "<feedback>" in out
