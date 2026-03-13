"""向后兼容测试：POST /ingest、/ingest/aliyun-sls、GET /index/status、GET /analysis/{id}。"""

from __future__ import annotations

import re


def test_post_ingest_returns_analysis_id(app_client):
    """TC-BC-001: POST /ingest 返回 analysis_id。"""
    r = app_client.post("/ingest", json={"service_name": "svc", "error_log": "err"})
    assert r.status_code == 200
    data = r.json()
    assert data.get("status") == "accepted"
    aid = data.get("analysis_id")
    assert aid is not None
    assert re.match(r"^[a-f0-9]{32}$", aid), "analysis_id 应为 32 位 hex"


def test_post_ingest_aliyun_sls_compat(app_client):
    """TC-BC-002: POST /ingest/aliyun-sls 兼容 SLS 格式。"""
    payload = {
        "content": "error msg",
        "__time__": 1234567890,
        "__tag__": {"_container_name": "my-svc"},
    }
    r = app_client.post("/ingest/aliyun-sls", json=payload)
    assert r.status_code == 200
    data = r.json()
    assert "analysis_id" in data or "status" in data


def test_get_index_status(app_client):
    """TC-BC-003: GET /index/status 返回各仓库状态。"""
    r = app_client.get("/index/status")
    assert r.status_code == 200
    data = r.json()
    assert "repos" in data or isinstance(data, (list, dict))


def test_get_analysis_returns_report_or_status(app_client):
    """TC-BC-004: GET /analysis/{id} 返回报告或状态。"""
    # 先 ingest 得到 analysis_id
    ingest_r = app_client.post("/ingest", json={"service_name": "svc", "error_log": "err"})
    assert ingest_r.status_code == 200
    aid = ingest_r.json().get("analysis_id")
    assert aid

    r = app_client.get(f"/analysis/{aid}")
    assert r.status_code == 200
    data = r.json()
    assert "status" in data or "summary" in data or "report" in data
