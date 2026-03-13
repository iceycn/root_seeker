"""format_tool_error 测试。"""

from root_seeker.mcp.format_response import format_tool_error, format_too_many_mistakes


def test_format_tool_error():
    out = format_tool_error("连接失败")
    assert "<error>" in out
    assert "连接失败" in out


def test_format_tool_error_with_tool_and_code():
    out = format_tool_error("超时", tool_name="code.search", error_code="TOOL_TIMEOUT")
    assert "code.search" in out
    assert "TOOL_TIMEOUT" in out


def test_format_too_many_mistakes():
    out = format_too_many_mistakes("请检查参数")
    assert "连续失败" in out
    assert "<feedback>" in out
