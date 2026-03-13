"""外部 MCP Server 测试：is_mcp_sdk_available、ENV 解析、工具名前缀。"""

from __future__ import annotations

import os
from unittest.mock import MagicMock

import pytest

from root_seeker.mcp.external_client import _mcp_tool_to_schema, _resolve_env, is_mcp_sdk_available


def test_is_mcp_sdk_available():
    """TC-EXT-001: is_mcp_sdk_available 返回 bool。"""
    result = is_mcp_sdk_available()
    assert isinstance(result, bool)


def test_resolve_env_prefix():
    """TC-EXT-002: ENV: 前缀环境变量解析。"""
    os.environ["TEST_MCP_VAR"] = "resolved_value"
    try:
        env = {"KEY": "ENV:TEST_MCP_VAR", "OTHER": "literal"}
        resolved = _resolve_env(env)
        assert resolved["KEY"] == "resolved_value"
        assert resolved["OTHER"] == "literal"
    finally:
        os.environ.pop("TEST_MCP_VAR", None)


def test_resolve_env_missing_var():
    """ENV: 引用不存在的变量返回空字符串。"""
    env = {"KEY": "ENV:NONEXISTENT_VAR_12345"}
    resolved = _resolve_env(env)
    assert resolved["KEY"] == ""


def test_external_tool_name_has_server_prefix():
    """TC-EXT-003: 外部工具名带 server 前缀。"""
    mock_tool = MagicMock()
    mock_tool.name = "query_logs"
    mock_tool.description = "查询日志"
    mock_tool.inputSchema = {}
    schema = _mcp_tool_to_schema(mock_tool, "aliyun")
    assert schema.name == "aliyun.query_logs"
    assert schema.description == "查询日志"
