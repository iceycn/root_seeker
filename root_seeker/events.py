"""任务完成事件与监听器。任务执行完成后触发，所有监听器可订阅。"""

from __future__ import annotations

import asyncio
import json
import logging
from dataclasses import dataclass
from typing import Any, Callable, Protocol

logger = logging.getLogger(__name__)


def _payload_to_markdown(payload: dict[str, Any]) -> str:
    """将 analysis payload（与 GET /analysis/{id} 一致）转为 Markdown。"""
    lines: list[str] = []
    lines.append(f"- analysis_id: {payload.get('analysis_id', '')}")
    if payload.get("created_at"):
        lines.append(f"- 时间: {payload['created_at']}")
    if payload.get("business_impact"):
        lines.append(f"- 业务影响: {payload['business_impact']}")
    lines.append("")
    lines.append("**摘要**")
    lines.append(payload.get("summary", ""))
    if payload.get("hypotheses"):
        lines.append("")
        lines.append("**可能原因**")
        for h in payload["hypotheses"][:8]:
            lines.append(f"- {h}")
    if payload.get("suggestions"):
        lines.append("")
        lines.append("**修改建议**")
        for s in payload["suggestions"][:10]:
            lines.append(f"- {s}")
    ev = payload.get("evidence") or {}
    files = ev.get("files") if isinstance(ev, dict) else []
    if files:
        lines.append("")
        lines.append("**关键证据**")
        for ef in files[:6]:
            loc = ef.get("file_path", "")
            if ef.get("start_line") and ef.get("end_line"):
                loc = f"{loc}:{ef['start_line']}-{ef['end_line']}"
            lines.append(f"- {loc}（{ef.get('source', '')}）")
    return "\n".join(lines)


@dataclass(frozen=True)
class AnalysisCompletedEvent:
    """分析任务完成事件。payload 与 GET /analysis/{id} 返回值结构一致。"""

    analysis_id: str
    status: str  # completed | failed
    payload: dict[str, Any]


class AnalysisCompletedListener(Protocol):
    """分析完成监听器协议。"""

    def on_analysis_completed(self, event: AnalysisCompletedEvent) -> None:
        """任务完成时调用。"""
        ...


class AnalysisEventBus:
    """分析完成事件总线，支持注册监听器并在任务完成时通知。"""

    def __init__(self) -> None:
        self._listeners: list[AnalysisCompletedListener | Callable[[AnalysisCompletedEvent], Any]] = []

    def add_listener(self, listener: AnalysisCompletedListener | Callable[[AnalysisCompletedEvent], Any]) -> None:
        """注册监听器。"""
        self._listeners.append(listener)

    def remove_listener(self, listener: AnalysisCompletedListener | Callable[[AnalysisCompletedEvent], Any]) -> None:
        """移除监听器。"""
        if listener in self._listeners:
            self._listeners.remove(listener)

    def emit(self, event: AnalysisCompletedEvent) -> None:
        """同步触发事件，通知所有监听器。"""
        for listener in self._listeners:
            try:
                if hasattr(listener, "on_analysis_completed"):
                    listener.on_analysis_completed(event)
                elif callable(listener):
                    listener(event)
            except Exception as e:
                logger.exception("[Events] 监听器执行异常: %s", e)


class LogListener:
    """默认日志监听器：将 AI 分析结果打印到日志，格式与 GET /analysis/{id} 返回值一致。"""

    def __init__(self, *, pretty: bool = True) -> None:
        self._pretty = pretty

    def on_analysis_completed(self, event: AnalysisCompletedEvent) -> None:
        payload_str = json.dumps(event.payload, ensure_ascii=False, indent=2) if self._pretty else json.dumps(
            event.payload, ensure_ascii=False
        )
        logger.info(
            "[AnalysisCompleted] analysis_id=%s status=%s\n%s",
            event.analysis_id,
            event.status,
            payload_str,
        )


class NotifierCompletionListener:
    """
    监听完成事件，将分析报告推送到配置的 Notifier（企业微信、钉钉等）。
    仅当 status=completed 且 payload 含 summary 时发送。
    """

    def __init__(self, notifiers: list) -> None:
        self._notifiers = notifiers or []

    def on_analysis_completed(self, event: AnalysisCompletedEvent) -> None:
        if event.status != "completed" or "summary" not in event.payload:
            return
        if not self._notifiers:
            return
        markdown = _payload_to_markdown(event.payload)
        service_name = event.payload.get("service_name", "unknown")
        title = f"错误分析：{service_name}"

        async def _send() -> None:
            for n in self._notifiers:
                try:
                    if hasattr(n, "send_markdown"):
                        await n.send_markdown(title=title, markdown=markdown)
                except Exception as e:
                    logger.warning("[NotifierCompletionListener] 推送失败: %s", e)

        try:
            loop = asyncio.get_running_loop()
            loop.create_task(_send())
        except RuntimeError:
            asyncio.run(_send())
