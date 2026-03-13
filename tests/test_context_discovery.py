"""上下文发现模块测试。"""

from __future__ import annotations

import pytest

from root_seeker.ai.context_discovery import (
    build_hints_for_plan,
    discover_refs_from_error_log,
    extract_class_method_names,
    extract_config_keys,
    extract_error_codes,
    extract_request_id,
    extract_trace_id,
)


def test_extract_trace_id():
    assert extract_trace_id('trace_id: 36dfc57c26a84cdcbdc608d8e1d31ee3') == "36dfc57c26a84cdcbdc608d8e1d31ee3"
    assert extract_trace_id('"trace_id": "abc123def456"') == "abc123def456"
    assert extract_trace_id("no trace here") is None


def test_extract_request_id():
    assert extract_request_id('request_id: abc123def456789') == "abc123def456789"
    assert extract_request_id("no request") is None


def test_extract_class_method_names():
    text = "at com.foo.BarService.baz(BarService.java:42)"
    assert "com.foo.BarService.baz" in extract_class_method_names(text)
    text2 = "at com.example.OrderController.getOrder(OrderController.java:100)"
    names = extract_class_method_names(text2)
    assert any("OrderController" in n for n in names)


def test_extract_config_keys():
    text = '"api_url": "http://foo", "db_config": "x"'
    keys = extract_config_keys(text)
    assert any("api_url" in k or "url" in k for k in keys)


def test_extract_error_codes():
    text = '"error_code": "invalid_order_item_id"'
    assert "invalid_order_item_id" in extract_error_codes(text)


def test_discover_refs_from_error_log():
    log = 'trace_id: abc123def456789\nat com.foo.Bar.baz(Bar.java:1)\n"error_code": "ERR_001"'
    refs = discover_refs_from_error_log(log)
    assert refs.get("trace_id") == ["abc123def456789"]
    assert refs.get("error_code")
    assert refs.get("class_method")


def test_build_hints_for_plan():
    refs = {"trace_id": ["x"], "class_method": ["com.foo.Bar.baz"]}
    hints = build_hints_for_plan(refs)
    assert "trace_id" in hints
    assert "correlation.get_info" in hints
    assert "code.search" in hints or "evidence.context_search" in hints
