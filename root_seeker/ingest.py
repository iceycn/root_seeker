"""日志摄入：通用 JSON 格式与各来源格式解析。"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from root_seeker.domain import IngestEvent, NormalizedErrorEvent


def parse_sls_record(raw: dict[str, Any]) -> IngestEvent:
    """从阿里云 SLS 单条原始记录解析为 IngestEvent。"""
    content = raw.get("content", "")
    tags = raw.get("__tag__", {}) if isinstance(raw.get("__tag__"), dict) else {}
    container = (
        tags.get("_container_name")
        or raw.get("__tag__:_container_name__")
        or raw.get("__tag__:_container_name_")
        or raw.get("_container_name")
    )
    if not container and " " in content:
        first = content.split("\n")[0].strip()
        parts = first.split()
        if len(parts) >= 3:
            container = parts[2]
    service_name = container or "unknown"
    ts = raw.get("__time__")
    if ts is not None:
        try:
            ts = datetime.fromtimestamp(int(ts), tz=timezone.utc)
        except Exception:
            ts = None
    return IngestEvent(
        service_name=service_name,
        error_log=content,
        query_key="default_error_context",
        timestamp=ts,
        tags={},
    )


def parse_single_log(raw: dict[str, Any]) -> IngestEvent | None:
    """解析单条日志为 IngestEvent，支持标准格式与 SLS 格式。"""
    if not isinstance(raw, dict):
        return None
    if "service_name" in raw and "error_log" in raw:
        try:
            return IngestEvent(
                service_name=str(raw["service_name"]),
                error_log=str(raw["error_log"]),
                query_key=str(raw.get("query_key", "default_error_context")),
                timestamp=_parse_timestamp(raw.get("timestamp")),
                tags=dict(raw.get("tags", {})) if isinstance(raw.get("tags"), dict) else {},
            )
        except Exception:
            return None
    if "content" in raw or "__time__" in raw:
        return parse_sls_record(raw)
    return None


def parse_log_list(body: list[dict[str, Any]] | dict[str, Any]) -> list[IngestEvent]:
    """解析日志列表为 IngestEvent 列表，支持标准格式与 SLS 格式。"""
    if isinstance(body, dict):
        body = [body]
    if not isinstance(body, list):
        return []
    events: list[IngestEvent] = []
    for item in body:
        if not isinstance(item, dict):
            continue
        ev = parse_single_log(item)
        if ev is not None:
            events.append(ev)
    return events


def parse_ingest_body(body: dict[str, Any] | list) -> IngestEvent | None:
    """
    解析请求体为 IngestEvent。
    - 若已是 IngestEvent 格式（含 service_name、error_log），直接构造。
    - 若为 SLS 原始格式（含 content、__time__），调用 parse_sls_record。
    - 若为列表，取首条解析。
    """
    if isinstance(body, list) and body:
        body = body[0]
    return parse_single_log(body) if isinstance(body, dict) else None


def _parse_timestamp(v: Any) -> datetime | None:
    if v is None:
        return None
    if isinstance(v, datetime):
        return v
    if isinstance(v, (int, float)):
        try:
            return datetime.fromtimestamp(int(v), tz=timezone.utc)
        except Exception:
            return None
    if isinstance(v, str):
        try:
            return datetime.fromisoformat(v.replace("Z", "+00:00"))
        except Exception:
            return None
    return None


def to_normalized_event(event: IngestEvent) -> NormalizedErrorEvent:
    """IngestEvent 转为 NormalizedErrorEvent。"""
    return NormalizedErrorEvent(
        service_name=event.service_name,
        error_log=event.error_log,
        query_key=event.query_key,
        timestamp=event.timestamp or datetime.now(tz=timezone.utc),
        tags=event.tags,
    )
