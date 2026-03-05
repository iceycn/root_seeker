"""Admin 回调接口集成测试：验证 /gitsource/index/callback 接收与响应。

需 Admin 在 http://localhost:8080 运行。若未运行则跳过。
覆盖所有 task_type：qdrant/zoekt/remove_qdrant/remove_zoekt/resync/sync。
"""
from __future__ import annotations

import os

import pytest
import requests

CALLBACK_URL = os.environ.get("ADMIN_CALLBACK_URL", "http://localhost:8080/gitsource/index/callback")
SN = "integration-test-all-events"


def _admin_available() -> bool:
    try:
        r = requests.post(CALLBACK_URL, json={}, timeout=2)
        return r.status_code in (200, 500)  # 能连上即可
    except Exception:
        return False


def _post(payload: dict) -> requests.Response:
    return requests.post(CALLBACK_URL, json=payload, timeout=5)


def _assert_ok(r: requests.Response) -> None:
    assert r.status_code == 200, f"expected 200, got {r.status_code}: {r.text}"


@pytest.mark.skipif(not _admin_available(), reason="Admin 未运行，跳过集成测试")
class TestCallbackIntegration:
    """验证回调接口接收、入队、返回。覆盖所有事件类型。"""

    def test_qdrant_completed(self) -> None:
        _assert_ok(_post(
            {"service_name": SN, "task_type": "qdrant", "status": "completed", "qdrant_indexed": 1, "qdrant_count": 10}
        ))

    def test_qdrant_failed(self) -> None:
        _assert_ok(_post({"service_name": SN, "task_type": "qdrant", "status": "failed"}))

    def test_zoekt_completed(self) -> None:
        _assert_ok(_post(
            {"service_name": SN, "task_type": "zoekt", "status": "completed", "zoekt_indexed": 1}
        ))

    def test_zoekt_failed(self) -> None:
        _assert_ok(_post({"service_name": SN, "task_type": "zoekt", "status": "failed"}))

    def test_remove_qdrant_completed(self) -> None:
        _assert_ok(_post(
            {"service_name": SN, "task_type": "remove_qdrant", "status": "completed", "qdrant_indexed": 0}
        ))

    def test_remove_qdrant_failed(self) -> None:
        _assert_ok(_post({"service_name": SN, "task_type": "remove_qdrant", "status": "failed"}))

    def test_remove_zoekt_completed(self) -> None:
        _assert_ok(_post(
            {"service_name": SN, "task_type": "remove_zoekt", "status": "completed", "zoekt_indexed": 0}
        ))

    def test_remove_zoekt_failed(self) -> None:
        _assert_ok(_post({"service_name": SN, "task_type": "remove_zoekt", "status": "failed"}))

    def test_resync_completed(self) -> None:
        _assert_ok(_post({
            "service_name": SN,
            "task_type": "resync",
            "status": "completed",
            "qdrant_indexed": 1,
            "qdrant_count": 20,
            "zoekt_indexed": 1,
        }))

    def test_resync_failed(self) -> None:
        _assert_ok(_post({"service_name": SN, "task_type": "resync", "status": "failed"}))

    def test_sync_completed(self) -> None:
        _assert_ok(_post({
            "service_name": SN,
            "task_type": "sync",
            "status": "completed",
            "qdrant_indexed": True,
            "qdrant_indexing": False,
            "qdrant_count": 30,
            "zoekt_indexed": True,
            "zoekt_indexing": False,
        }))

    def test_empty_service_name_ignored(self) -> None:
        _assert_ok(_post({"service_name": "", "task_type": "qdrant", "status": "completed"}))

    def test_empty_payload(self) -> None:
        _assert_ok(_post({}))
