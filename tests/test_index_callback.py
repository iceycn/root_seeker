"""索引回调单元测试：验证事件 payload 与 Admin 对接字段。"""
from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, patch

from root_seeker.events import (
    IndexCallbackTrigger,
    QdrantIndexCompletedEvent,
    QdrantIndexRemovedEvent,
    ZoektIndexCompletedEvent,
    ZoektIndexRemovedEvent,
)


def _assert_payload_keys(payload: dict, required: list[str]) -> None:
    for k in required:
        assert k in payload, f"payload 缺少字段: {k}"


class TestIndexCallbackTriggerPayload:
    """验证 IndexCallbackTrigger 各事件生成的 payload 格式与 Admin 期望一致。"""

    def test_qdrant_completed_payload(self) -> None:
        captured: list[tuple] = []

        async def _capture(url: str, p: dict) -> None:
            captured.append((url, p))

        trigger = IndexCallbackTrigger()
        event = QdrantIndexCompletedEvent(
            service_name="api-distribution",
            repo_local_dir="/tmp/repo",
            indexed_chunks=100,
            status="completed",
            callback_url="http://localhost:8080/cb",
        )

        async def _run() -> None:
            with patch("root_seeker.indexing.callback.fire_callback", side_effect=_capture):
                trigger.on_qdrant_index_completed(event)
                await asyncio.sleep(0.05)

        asyncio.run(_run())
        assert len(captured) == 1
        url, payload = captured[0]
        assert url == "http://localhost:8080/cb"
        _assert_payload_keys(payload, ["service_name", "task_type", "status", "qdrant_indexed", "qdrant_count"])
        assert payload["service_name"] == "api-distribution"
        assert payload["task_type"] == "qdrant"
        assert payload["status"] == "completed"
        assert payload["qdrant_indexed"] == 1
        assert payload["qdrant_count"] == 100

    def test_qdrant_failed_payload(self) -> None:
        captured: list[tuple] = []

        async def _capture(url: str, p: dict) -> None:
            captured.append((url, p))

        trigger = IndexCallbackTrigger()
        event = QdrantIndexCompletedEvent(
            service_name="api-distribution",
            repo_local_dir="/tmp/repo",
            indexed_chunks=0,
            status="failed",
            error="index error",
            callback_url="http://localhost:8080/cb",
        )

        async def _run() -> None:
            with patch("root_seeker.indexing.callback.fire_callback", side_effect=_capture):
                with patch("root_seeker.events.asyncio.get_running_loop") as mock_loop:
                    mock_loop.return_value.create_task = lambda coro: asyncio.ensure_future(coro)
                    trigger.on_qdrant_index_completed(event)
                    await asyncio.sleep(0.02)

        asyncio.run(_run())
        assert len(captured) == 1
        _, payload = captured[0]
        assert payload["status"] == "failed"
        assert payload["qdrant_indexed"] == 0
        assert payload.get("error") == "index error"

    def test_zoekt_completed_payload(self) -> None:
        captured: list[tuple] = []

        async def _capture(url: str, p: dict) -> None:
            captured.append((url, p))

        trigger = IndexCallbackTrigger()
        event = ZoektIndexCompletedEvent(
            service_name="api-distribution",
            repo_local_dir="/tmp/repo",
            status="completed",
            callback_url="http://localhost:8080/cb",
        )

        async def _run() -> None:
            with patch("root_seeker.indexing.callback.fire_callback", side_effect=_capture):
                with patch("root_seeker.events.asyncio.get_running_loop") as mock_loop:
                    mock_loop.return_value.create_task = lambda coro: asyncio.ensure_future(coro)
                    trigger.on_zoekt_index_completed(event)
                    await asyncio.sleep(0.02)

        asyncio.run(_run())
        assert len(captured) == 1
        _, payload = captured[0]
        _assert_payload_keys(payload, ["service_name", "task_type", "status", "zoekt_indexed"])
        assert payload["task_type"] == "zoekt"
        assert payload["zoekt_indexed"] == 1

    def test_remove_qdrant_payload(self) -> None:
        captured: list[tuple] = []

        async def _capture(url: str, p: dict) -> None:
            captured.append((url, p))

        trigger = IndexCallbackTrigger()
        event = QdrantIndexRemovedEvent(
            service_name="api-distribution",
            status="completed",
            callback_url="http://localhost:8080/cb",
        )

        async def _run() -> None:
            with patch("root_seeker.indexing.callback.fire_callback", side_effect=_capture):
                with patch("root_seeker.events.asyncio.get_running_loop") as mock_loop:
                    mock_loop.return_value.create_task = lambda coro: asyncio.ensure_future(coro)
                    trigger.on_qdrant_index_removed(event)
                    await asyncio.sleep(0.02)

        asyncio.run(_run())
        assert len(captured) == 1
        _, payload = captured[0]
        assert payload["task_type"] == "remove_qdrant"
        assert payload["qdrant_indexed"] == 0

    def test_remove_zoekt_payload(self) -> None:
        captured: list[tuple] = []

        async def _capture(url: str, p: dict) -> None:
            captured.append((url, p))

        trigger = IndexCallbackTrigger()
        event = ZoektIndexRemovedEvent(
            service_name="api-distribution",
            status="completed",
            callback_url="http://localhost:8080/cb",
        )

        async def _run() -> None:
            with patch("root_seeker.indexing.callback.fire_callback", side_effect=_capture):
                with patch("root_seeker.events.asyncio.get_running_loop") as mock_loop:
                    mock_loop.return_value.create_task = lambda coro: asyncio.ensure_future(coro)
                    trigger.on_zoekt_index_removed(event)
                    await asyncio.sleep(0.02)

        asyncio.run(_run())
        assert len(captured) == 1
        _, payload = captured[0]
        assert payload["task_type"] == "remove_zoekt"
        assert payload["zoekt_indexed"] == 0

    def test_no_callback_url_skips_fire(self) -> None:
        trigger = IndexCallbackTrigger()
        event = QdrantIndexCompletedEvent(
            service_name="api-distribution",
            repo_local_dir="/tmp/repo",
            indexed_chunks=100,
            status="completed",
            callback_url=None,
        )
        with patch("root_seeker.indexing.callback.fire_callback") as mock_fire:
            trigger.on_qdrant_index_completed(event)
        mock_fire.assert_not_called()

    def test_empty_callback_url_skips_fire(self) -> None:
        trigger = IndexCallbackTrigger()
        event = QdrantIndexCompletedEvent(
            service_name="api-distribution",
            repo_local_dir="/tmp/repo",
            indexed_chunks=100,
            status="completed",
            callback_url="   ",
        )
        with patch("root_seeker.indexing.callback.fire_callback") as mock_fire:
            trigger.on_qdrant_index_completed(event)
        mock_fire.assert_not_called()


class TestFireCallback:
    """验证 fire_callback 解码 URL 并正确 POST。"""

    def test_fire_callback_decodes_url(self) -> None:
        from root_seeker.indexing.callback import fire_callback

        mock_client = AsyncMock()
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=None)
        mock_client.post = AsyncMock(return_value=type("R", (), {"status_code": 200})())

        with patch("httpx.AsyncClient", return_value=mock_client):
            encoded = "http%3A%2F%2Flocalhost%3A8080%2Fgitsource%2Findex%2Fcallback"
            asyncio.run(
                fire_callback(encoded, {"service_name": "test", "task_type": "qdrant", "status": "completed"})
            )

            call_url = mock_client.post.call_args[0][0]
            assert call_url == "http://localhost:8080/gitsource/index/callback"
            assert mock_client.post.call_args[1]["json"]["service_name"] == "test"
