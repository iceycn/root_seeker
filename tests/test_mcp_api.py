"""MCP API 集成测试：GET /mcp/tools、POST /mcp/call。"""

from __future__ import annotations

from root_seeker.mcp.protocol import ErrorCode


def test_get_mcp_tools_returns_list(app_client):
    """TC-MCP-001: GET /mcp/tools 返回工具列表。"""
    r = app_client.get("/mcp/tools")
    assert r.status_code == 200
    data = r.json()
    assert "tools" in data
    tools = data["tools"]
    assert isinstance(tools, list)
    assert len(tools) >= 5
    names = {t["name"] for t in tools}
    assert "code.read" in names
    assert "index.get_status" in names
    assert "correlation.get_info" in names
    assert "deps.get_graph" in names
    assert "analysis.run" in names
    assert "analysis.run_full" in names
    assert "analysis.synthesize" in names
    assert "evidence.context_search" in names
    for t in tools:
        assert "name" in t
        assert "description" in t
        assert "inputSchema" in t


def test_post_mcp_call_index_get_status(app_client):
    """TC-MCP-002: POST /mcp/call 执行 index.get_status 并返回。"""
    r = app_client.post("/mcp/call", json={"name": "index.get_status", "args": {}})
    assert r.status_code == 200
    data = r.json()
    assert "content" in data
    assert "isError" in data
    assert isinstance(data["content"], list)


def test_post_mcp_call_tool_not_found(app_client):
    """TC-MCP-003: POST /mcp/call 工具不存在返回 TOOL_NOT_FOUND。"""
    r = app_client.post("/mcp/call", json={"name": "nonexistent.tool", "args": {}})
    assert r.status_code == 200
    data = r.json()
    assert data["isError"] is True
    assert data.get("errorCode") == ErrorCode.TOOL_NOT_FOUND


def test_post_mcp_call_invalid_params(app_client):
    """TC-MCP-004: POST /mcp/call 缺参返回 INVALID_PARAMS。"""
    # analysis.run 需要 error_event，缺参时返回 INVALID_PARAMS
    r = app_client.post("/mcp/call", json={"name": "analysis.run", "args": {}})
    assert r.status_code == 200
    data = r.json()
    assert data["isError"] is True
    assert data.get("errorCode") == ErrorCode.INVALID_PARAMS
    text = (data["content"][0].get("text") or "") if data["content"] else ""
    assert "缺少" in text or "error_event" in text.lower()
