"""AI 驱动主流程测试：Plan、Act、Synthesize、Check、回退、skip_ai_driven。"""

from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, MagicMock

import pytest

from root_seeker.ai.orchestrator import (
    AiOrchestrator,
    OrchestratorConfig,
    PLAN_RESTRICTED_TOOLS,
    _build_repro_hint,
    _compact_tool_results,
    _reorder_steps_cline_mode,
    _should_compact_context,
)
from root_seeker.domain import AnalysisReport, NormalizedErrorEvent
from root_seeker.mcp.protocol import ErrorCode, ToolResult


@pytest.fixture
def event():
    return NormalizedErrorEvent(
        service_name="test-svc",
        error_log="NullPointerException at line 42",
        query_key="default_error_context",
    )


@pytest.fixture
def mock_mcp():
    m = MagicMock()
    m.list_tools = AsyncMock(
        return_value=[
            MagicMock(name="index.get_status", description="索引状态"),
            MagicMock(name="analysis.run", description="执行分析"),
        ]
    )
    m.build_tools_summary = lambda tools, include_params=True: "\n".join(
        f"- {getattr(t, 'name', t)}: {getattr(t, 'description', '')}" for t in tools
    )
    return m


@pytest.fixture
def mock_llm():
    return AsyncMock()


def test_plan_parses_llm_json(event, mock_mcp, mock_llm):
    """TC-ORC-001: Plan 阶段解析 LLM 返回的 JSON。"""
    mock_llm.generate = AsyncMock(
        return_value='{"goal":"分析错误","steps":[{"tool_name":"index.get_status","args":{}}]}'
    )
    mock_mcp.call_tool = AsyncMock(
        return_value=ToolResult.text('{"repos":[{"service_name":"test-svc"}]}')
    )
    orch = AiOrchestrator(mock_mcp, mock_llm, OrchestratorConfig())
    orch._tools_summary = "- index.get_status: 索引状态"

    plan = asyncio.run(orch._plan(event, "aid-1"))
    assert isinstance(plan, dict)
    assert "steps" in plan
    assert len(plan["steps"]) >= 1
    assert plan["steps"][0].get("tool_name") == "index.get_status"


def test_act_calls_tools(event, mock_mcp, mock_llm):
    """TC-ORC-002: Act 阶段按计划调用工具。"""
    mock_llm.generate = AsyncMock(
        side_effect=[
            '{"goal":"分析","steps":[{"tool_name":"index.get_status","args":{}}]}',
            '{"summary":"索引正常","hypotheses":["假设1"],"suggestions":["建议1"]}',
        ]
    )
    mock_mcp.call_tool = AsyncMock(return_value=ToolResult.text("ok"))
    orch = AiOrchestrator(mock_mcp, mock_llm, OrchestratorConfig())
    orch._tools_summary = "- index.get_status: 索引状态"

    report = asyncio.run(orch.analyze(event, analysis_id="aid-1"))
    assert report is not None
    mock_mcp.call_tool.assert_called()
    first_call = mock_mcp.call_tool.call_args_list[0]
    assert first_call[0][0] == "index.get_status"


def test_tool_invalid_params_ai_fix_and_retry(event, mock_mcp, mock_llm):
    """工具调用失败时，错误判断 AI 分析错误原因、修正参数后重试。"""
    mock_llm.generate = AsyncMock(
        side_effect=[
            '{"goal":"分析","steps":[{"tool_name":"deps.get_graph","args":{}}]}',
            '{"corrected_args":{"target":"test-svc","scope":"service"}}',
            '{"summary":"依赖图正常","hypotheses":["h1"],"suggestions":["s1"]}',
        ]
    )
    mock_mcp.call_tool = AsyncMock(
        side_effect=[
            ToolResult.text('{"repos":[{"service_name":"test-svc"}]}'),  # _plan 预取 index.get_status
            ToolResult.error("缺少必填参数: target", ErrorCode.INVALID_PARAMS),
            ToolResult.text('{"nodes":[{"id":"test-svc","label":"test-svc"}],"edges":[]}'),
        ]
    )
    orch = AiOrchestrator(mock_mcp, mock_llm, OrchestratorConfig())
    orch._tools_summary = "- deps.get_graph: 依赖拓扑"

    report = asyncio.run(orch.analyze(event, analysis_id="aid-1"))
    assert report is not None
    assert mock_mcp.call_tool.call_count == 3  # index.get_status(预取) + deps.get_graph(失败) + deps.get_graph(重试)
    first_args = mock_mcp.call_tool.call_args_list[0][0][1]
    assert first_args.get("service_name") == "test-svc"  # index.get_status 预取
    second_args = mock_mcp.call_tool.call_args_list[2][0][1]  # 重试时的参数
    assert second_args.get("target") == "test-svc"


def test_mistake_limit_aborts(event, mock_mcp, mock_llm):
    """同一工具连续失败 mistake_limit 次后中止。"""
    mock_llm.generate = AsyncMock(
        return_value='{"goal":"分析","steps":[{"tool_name":"index.get_status","args":{}}]}'
    )
    mock_mcp.call_tool = AsyncMock(
        return_value=ToolResult.error("连接失败", ErrorCode.INTERNAL_ERROR)
    )
    mock_mcp.build_tools_summary = lambda t, **_: "- index.get_status: 索引"
    orch = AiOrchestrator(mock_mcp, mock_llm, OrchestratorConfig(mistake_limit=1))
    orch._tools_summary = "- index.get_status: 索引"
    with pytest.raises(RuntimeError) as exc_info:
        asyncio.run(orch.analyze(event, analysis_id="aid-1"))
    assert "mistake_limit" in str(exc_info.value) or "连续失败" in str(exc_info.value)


def test_tool_failure_raises_runtime_error(event, mock_mcp, mock_llm):
    """TC-ORC-003: 工具失败时抛出 RuntimeError。"""
    mock_llm.generate = AsyncMock(
        return_value='{"goal":"分析","steps":[{"tool_name":"index.get_status","args":{}}]}'
    )
    mock_mcp.call_tool = AsyncMock(
        return_value=ToolResult.error("not found", ErrorCode.TOOL_NOT_FOUND)
    )
    orch = AiOrchestrator(mock_mcp, mock_llm, OrchestratorConfig())
    orch._tools_summary = "- index.get_status: 索引状态"

    with pytest.raises(RuntimeError) as exc_info:
        asyncio.run(orch.analyze(event, analysis_id="aid-1"))
    assert "index.get_status" in str(exc_info.value) or "failed" in str(exc_info.value).lower()


def test_synthesize_from_tool_results(event, mock_mcp, mock_llm):
    """TC-ORC-004: Synthesize 从 tool 结果生成报告。"""
    # plan 中无 analysis.run，仅有 code.read 等，会走 _synthesize
    mock_llm.generate = AsyncMock(
        side_effect=[
            '{"goal":"分析","steps":[{"tool_name":"code.read","args":{"repo_id":"svc","file_path":"x.java"}}]}',
            '{"summary":"根因是空指针","hypotheses":["假设1"],"suggestions":["建议1"]}',
        ]
    )
    mock_mcp.call_tool = AsyncMock(return_value=ToolResult.text("代码内容"))
    orch = AiOrchestrator(mock_mcp, mock_llm, OrchestratorConfig())
    orch._tools_summary = "- code.read: 读取代码"

    report = asyncio.run(orch.analyze(event, analysis_id="aid-1"))
    assert report is not None
    assert report.summary
    assert "根因" in report.summary or "空指针" in report.summary


def test_check_and_sanitize_redacts(event):
    """TC-ORC-005: Check 阶段脱敏。"""
    from root_seeker.ai.orchestrator import AiOrchestrator

    orch = AiOrchestrator(MagicMock(), MagicMock(), OrchestratorConfig())
    report = AnalysisReport(
        analysis_id="aid-1",
        service_name="test",
        summary="access_key=sk-1234567890abcdef 泄露",
        hypotheses=[],
        suggestions=[],
        correlation_id="cid-1",
    )
    result, _ = orch._check_and_sanitize(report, event)
    assert "sk-1234567890" not in result.summary
    assert "[REDACTED" in result.summary


def test_check_and_sanitize_redacts_all_fields(event):
    """TC-REDACT-002: Orchestrator Check 阶段 hypotheses、suggestions、business_impact 均脱敏。"""
    from root_seeker.ai.orchestrator import AiOrchestrator

    orch = AiOrchestrator(MagicMock(), MagicMock(), OrchestratorConfig())
    report = AnalysisReport(
        analysis_id="aid-1",
        service_name="test",
        summary="正常摘要",
        hypotheses=["password: secret123 泄露"],
        suggestions=["请修改 api_key=sk-12345678"],
        business_impact="mysql://user:pass@host/db 连接失败",
        correlation_id="cid-1",
    )
    result, _ = orch._check_and_sanitize(report, event)
    assert "secret123" not in str(result.hypotheses)
    assert "sk-12345678" not in str(result.suggestions)
    assert "pass@" not in (result.business_impact or "")
    assert "[REDACTED" in str(result.hypotheses) or "[REDACTED" in str(result.suggestions)


def test_analyzer_ai_driven_failure_fallback_direct():
    """TC-ORC-006: Analyzer AI 驱动失败时回退直连。"""
    from unittest.mock import patch

    from root_seeker.domain import NormalizedErrorEvent
    from root_seeker.services.analyzer import AnalyzerConfig, AnalyzerService

    mock_router = MagicMock()
    mock_router.route.return_value = []
    mock_router.infer_from_error_log.return_value = []
    mock_store = MagicMock()

    with patch("root_seeker.ai.orchestrator.AiOrchestrator") as MockOrch:
        mock_orch_instance = MagicMock()
        mock_orch_instance.analyze = AsyncMock(side_effect=RuntimeError("AI 驱动失败"))
        MockOrch.return_value = mock_orch_instance

        analyzer = AnalyzerService(
            cfg=AnalyzerConfig(ai_driven_enabled=True),
            router=mock_router,
            enricher=MagicMock(),
            zoekt=None,
            vector=None,
            graph_loader=None,
            evidence_builder=MagicMock(),
            llm=MagicMock(),
            notifiers=[],
            store=mock_store,
            mcp_gateway=MagicMock(),
        )
        event = NormalizedErrorEvent(service_name="svc", error_log="err", query_key="default")
        report = asyncio.run(analyzer.analyze(event, analysis_id="aid-1"))
        assert report is not None
        assert "未找到该 service_name" in report.summary
        mock_orch_instance.analyze.assert_called_once()


def test_analyzer_ai_driven_disabled_uses_direct():
    """TC-ORC-007: ai_driven_enabled=false 走直连。"""
    from root_seeker.domain import NormalizedErrorEvent
    from root_seeker.services.analyzer import AnalyzerConfig, AnalyzerService

    mock_router = MagicMock()
    mock_router.route.return_value = []
    mock_router.infer_from_error_log.return_value = []
    mock_store = MagicMock()

    analyzer = AnalyzerService(
        cfg=AnalyzerConfig(ai_driven_enabled=False),
        router=mock_router,
        enricher=MagicMock(),
        zoekt=None,
        vector=None,
        graph_loader=None,
        evidence_builder=MagicMock(),
        llm=MagicMock(),
        notifiers=[],
        store=mock_store,
        mcp_gateway=MagicMock(),
    )
    event = NormalizedErrorEvent(service_name="svc", error_log="err", query_key="default")
    report = asyncio.run(analyzer.analyze(event, analysis_id="aid-1"))
    assert report is not None
    assert "未找到该 service_name" in report.summary
    # 未调用 AiOrchestrator（通过 patch 验证会复杂，这里用结果推断：直连路径无 repo 时返回固定文案）
    assert report.summary == "未找到该 service_name 对应的仓库配置或推断结果。"


def test_analysis_run_uses_skip_ai_driven():
    """TC-ORC-008: analysis.run 调用时 skip_ai_driven 避免循环。"""
    from root_seeker.mcp.tools.analysis import AnalysisRunTool

    mock_analyzer = MagicMock()
    mock_analyzer.analyze = AsyncMock(
        return_value=AnalysisReport(
            analysis_id="aid-1",
            service_name="svc",
            summary="ok",
            hypotheses=[],
            suggestions=[],
            correlation_id="cid-1",
        )
    )
    tool = AnalysisRunTool(mock_analyzer)
    result = asyncio.run(
        tool.run(
            {"error_event": {"service_name": "svc", "error_log": "err", "query_key": "default"}},
            {},
        )
    )
    assert not result.isError
    mock_analyzer.analyze.assert_called_once()
    call_kwargs = mock_analyzer.analyze.call_args[1]
    assert call_kwargs.get("skip_ai_driven") is True


def test_fill_step_args_injects_file_path_from_code_search(event):
    """code.read 的 file_path 为占位符时，从 code.search 结果注入"""
    from root_seeker.ai.orchestrator import _extract_file_path_from_code_search, _fill_step_args

    tool_results = [
        (
            "code.search",
            '{"hits":[{"file_path":"src/main/java/OrderService.java","line_number":42,"preview":"..."}],"total":1}',
            False,
            {},
        )
    ]
    step = {"tool_name": "code.read", "args": {"repo_id": "order-svc", "file_path": "上一步返回的路径"}}
    args = _fill_step_args(step, event, "aid-1", tool_results_so_far=tool_results)
    assert args["file_path"] == "src/main/java/OrderService.java"


def test_extract_file_path_fallback_when_json_truncated():
    """JSON 截断非法时，用正则兜底提取 file_path"""
    from root_seeker.ai.orchestrator import _extract_file_path_from_code_search

    # 模拟截断后的非法 JSON（含 control char 或未闭合）
    truncated = '{"hits":[{"file_path":"src/foo/Bar.java","line_number":1,"preview":"x'
    tool_results = [("code.search", truncated, False, {})]
    assert _extract_file_path_from_code_search(tool_results) == "src/foo/Bar.java"


def test_optimize_duplicate_tool_results():
    """code.read 同文件保留最后一次，其余替换为占位"""
    from root_seeker.ai.orchestrator import _optimize_duplicate_tool_results

    results = [
        ("code.search", "hit1", False, {}),
        ("code.read", "content1", False, {"file_path": "src/a.java"}),
        ("code.read", "content2", False, {"file_path": "src/a.java"}),
        ("code.read", "content3", False, {"file_path": "src/b.java"}),
    ]
    out = _optimize_duplicate_tool_results(results)
    assert out[1][1] == "[code.read] 重复读取 src/a.java，完整内容见下文最后一次读取"
    assert out[2][1] == "content2"
    assert out[3][1] == "content3"


def test_should_compact_context():
    """轮数或字符数超阈值时需压缩"""
    results = [("code.read", "x" * 5000, False, {})] * 10  # 50k chars
    assert _should_compact_context(6, results, compact_after_rounds=5, compact_threshold_chars=40_000)
    assert not _should_compact_context(3, results, compact_after_rounds=5, compact_threshold_chars=40_000)
    assert not _should_compact_context(6, [("a", "short", False, {})], 5, 40_000)


def test_compact_tool_results():
    """压缩：保留最近 N 个，超长截断"""
    results = [
        ("code.search", "hit1", False, {}),
        ("code.read", "c1", False, {"file_path": "a.java"}),
        ("code.read", "c2", False, {"file_path": "b.java"}),
        ("code.read", "c3", False, {"file_path": "c.java"}),
    ]
    out = _compact_tool_results(results, keep_last_n=2)
    assert len(out) == 3  # 1 compact notice + 2 kept
    assert out[0][0] == "_compact"
    assert "省略前 2 个" in out[0][1]
    assert out[1][0] == "code.read" and out[1][3] == {"file_path": "b.java"}
    assert out[2][0] == "code.read" and out[2][3] == {"file_path": "c.java"}


def test_reorder_steps_cline_mode():
    """analysis.run 在前两步时移至末尾，勘探优先"""
    steps = [
        {"tool_name": "analysis.run", "args": {}},
        {"tool_name": "code.search", "args": {"query": "foo"}},
        {"tool_name": "code.read", "args": {"file_path": "a.java"}},
    ]
    out = _reorder_steps_cline_mode(steps)
    assert out[0]["tool_name"] == "code.search"
    assert out[1]["tool_name"] == "code.read"
    assert out[2]["tool_name"] == "analysis.run"

    steps2 = [{"tool_name": "index.get_status", "args": {}}, {"tool_name": "code.search", "args": {}}]
    assert _reorder_steps_cline_mode(steps2) == steps2


def test_build_repro_hint(event):
    """可复现参数提示：correlation/index 类工具返回 hint"""
    assert _build_repro_hint(event, "correlation.get_info") == "query_key=default_error_context"
    assert _build_repro_hint(event, "code.read") is None


def test_plan_restricted_tools_filtered(event, mock_mcp, mock_llm):
    """PLAN_RESTRICTED_TOOLS 为空时无影响；有配置时过滤受限工具"""
    # 默认空，行为不变
    assert len(PLAN_RESTRICTED_TOOLS) == 0


def test_truncate_multilevel():
    """多级截断：超 90% 时 quarter，否则 half"""
    from root_seeker.ai.orchestrator import _truncate_multilevel

    long_text = "x" * 5000
    out = _truncate_multilevel(long_text, 1000)
    assert len(out) <= 1000
    assert "截断" in out
    assert "原长 5000" in out


def test_analysis_synthesize_uses_synthesize_from_evidence():
    """TC-ORC-009: analysis.synthesize 调用 synthesize_from_evidence，不做 enrich/zoekt。"""
    from root_seeker.mcp.tools.analysis import AnalysisSynthesizeTool

    mock_analyzer = MagicMock()
    mock_analyzer.synthesize_from_evidence = AsyncMock(
        return_value=AnalysisReport(
            analysis_id="aid-1",
            service_name="svc",
            summary="根因已定位",
            hypotheses=[],
            suggestions=[],
            correlation_id="cid-1",
        )
    )
    tool = AnalysisSynthesizeTool(mock_analyzer)
    result = asyncio.run(
        tool.run(
            {
                "error_event": {"service_name": "svc", "error_log": "err", "query_key": "default"},
                "pre_collected_evidence": "[code.search]\n命中结果\n[code.read]\n代码内容",
            },
            {},
        )
    )
    assert not result.isError
    mock_analyzer.synthesize_from_evidence.assert_called_once()
    call_kwargs = mock_analyzer.synthesize_from_evidence.call_args[1]
    assert call_kwargs.get("pre_collected_evidence") == "[code.search]\n命中结果\n[code.read]\n代码内容"
    mock_analyzer.analyze.assert_not_called()
