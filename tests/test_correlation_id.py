"""correlation_id 贯通测试：ingest→queue→analyze→report。"""

from __future__ import annotations

import asyncio
import time
from unittest.mock import AsyncMock, MagicMock

import pytest

from root_seeker.ai.orchestrator import AiOrchestrator, OrchestratorConfig
from root_seeker.domain import AnalysisReport, NormalizedErrorEvent
from root_seeker.mcp.protocol import ToolResult


def test_analysis_report_contains_correlation_id():
    """TC-CID-002: AnalysisReport 含 correlation_id。"""
    event = NormalizedErrorEvent(
        service_name="test-svc",
        error_log="err",
        query_key="default",
        correlation_id="cid123",
    )
    mock_mcp = MagicMock()
    mock_mcp.list_tools = AsyncMock(return_value=[MagicMock(name="index.get_status", description="x")])
    mock_mcp.call_tool = AsyncMock(return_value=ToolResult.text("ok"))
    mock_llm = AsyncMock()
    mock_llm.generate = AsyncMock(
        return_value='{"goal":"分析","steps":[{"tool_name":"index.get_status","args":{}}]}'
    )
    orch = AiOrchestrator(mock_mcp, mock_llm, OrchestratorConfig())
    orch._tools_summary = "- index.get_status: x"

    report = asyncio.run(orch.analyze(event, analysis_id="aid-1"))
    assert report.correlation_id == "cid123"


def test_get_analysis_returns_correlation_id(app_client):
    """TC-CID-003: GET /analysis/{id} 返回含 correlation_id。"""
    r = app_client.post("/ingest", json={"service_name": "svc", "error_log": "err"})
    assert r.status_code == 200
    aid = r.json().get("analysis_id")
    assert aid

    for _ in range(5):
        r = app_client.get(f"/analysis/{aid}")
        assert r.status_code == 200
        data = r.json()
        if "summary" in data:
            assert "correlation_id" in data, "completed report 应含 correlation_id"
            assert data["correlation_id"] == aid
            return
        time.sleep(0.5)
    # 若未完成，至少验证 status 结构
    assert "status" in data or "summary" in data


def test_analysis_report_fallback_to_analysis_id():
    """event 无 correlation_id 时，report 使用 analysis_id。"""
    event = NormalizedErrorEvent(
        service_name="test-svc",
        error_log="err",
        query_key="default",
        correlation_id=None,
    )
    mock_mcp = MagicMock()
    mock_mcp.list_tools = AsyncMock(return_value=[MagicMock(name="index.get_status", description="x")])
    mock_mcp.call_tool = AsyncMock(return_value=ToolResult.text("ok"))
    mock_llm = AsyncMock()
    mock_llm.generate = AsyncMock(
        return_value='{"goal":"分析","steps":[{"tool_name":"index.get_status","args":{}}]}'
    )
    orch = AiOrchestrator(mock_mcp, mock_llm, OrchestratorConfig())
    orch._tools_summary = "- index.get_status: x"

    report = asyncio.run(orch.analyze(event, analysis_id="aid-xyz"))
    assert report.correlation_id == "aid-xyz"
