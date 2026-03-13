"""redact_sensitive 脱敏工具测试。"""

from unittest.mock import MagicMock

from root_seeker.domain import AnalysisReport
from root_seeker.services.analyzer import AnalyzerConfig, AnalyzerService
from root_seeker.utils import redact_sensitive


def test_sanitize_report_redacts_summary():
    """TC-REDACT-001: _sanitize_report 保存前脱敏。"""
    analyzer = AnalyzerService(
        cfg=AnalyzerConfig(),
        router=MagicMock(),
        enricher=MagicMock(),
        zoekt=None,
        vector=None,
        graph_loader=None,
        evidence_builder=MagicMock(),
        llm=None,
        notifiers=[],
        store=MagicMock(),
    )
    report = AnalysisReport(
        analysis_id="aid-1",
        service_name="svc",
        summary="access_key=sk-1234567890abcdef 泄露",
        hypotheses=[],
        suggestions=[],
        correlation_id="cid-1",
    )
    result = analyzer._sanitize_report(report)
    assert "sk-1234567890" not in result.summary
    assert "[REDACTED" in result.summary


def test_redact_access_key():
    t = "access_key=sk-1234567890abcdef"
    assert "[REDACTED:key]" in redact_sensitive(t)
    assert "sk-1234567890" not in redact_sensitive(t)


def test_redact_password():
    t = "password: mySecret123"
    assert "[REDACTED:secret]" in redact_sensitive(t)
    assert "mySecret123" not in redact_sensitive(t)


def test_redact_bearer_token():
    t = "Authorization: Bearer eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9"
    assert "[REDACTED:token]" in redact_sensitive(t)


def test_redact_connection_string():
    t = "mysql://user:pass@localhost:3306/db"
    assert "[REDACTED:connection]" in redact_sensitive(t)


def test_redact_preserves_safe_text():
    t = "正常分析结论：空指针异常"
    assert redact_sensitive(t) == t


def test_redact_empty():
    assert redact_sensitive("") == ""
    assert redact_sensitive(None) == ""
