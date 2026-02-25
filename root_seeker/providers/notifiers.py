from __future__ import annotations

import logging
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol

import httpx

logger = logging.getLogger(__name__)


class Notifier(Protocol):
    async def send_markdown(self, *, title: str, markdown: str) -> None: ...


@dataclass(frozen=True)
class WeComNotifierConfig:
    webhook_url: str


class WeComNotifier:
    def __init__(self, cfg: WeComNotifierConfig, client: httpx.AsyncClient | None = None):
        self._cfg = cfg
        self._client = client or httpx.AsyncClient(timeout=10.0)

    async def send_markdown(self, *, title: str, markdown: str) -> None:
        payload = {
            "msgtype": "markdown",
            "markdown": {
                "content": f"### {title}\n{markdown}",
            },
        }
        resp = await self._client.post(str(self._cfg.webhook_url), json=payload)
        resp.raise_for_status()


@dataclass(frozen=True)
class DingTalkNotifierConfig:
    webhook_url: str


class DingTalkNotifier:
    def __init__(self, cfg: DingTalkNotifierConfig, client: httpx.AsyncClient | None = None):
        self._cfg = cfg
        self._client = client or httpx.AsyncClient(timeout=10.0)

    async def send_markdown(self, *, title: str, markdown: str) -> None:
        payload = {
            "msgtype": "markdown",
            "markdown": {
                "title": title,
                "text": markdown,
            },
        }
        resp = await self._client.post(str(self._cfg.webhook_url), json=payload)
        resp.raise_for_status()


class ConsoleNotifier:
    """将 Markdown 报告打印到控制台（通过 logging），便于调试或配置开启时查看。"""

    async def send_markdown(self, *, title: str, markdown: str) -> None:
        logger.info("--- 分析报告 ---\n%s\n%s", title, markdown)


@dataclass(frozen=True)
class FileReportStoreNotifierConfig:
    path: str | Path


class FileReportStoreNotifier:
    """将 Markdown 报告追加写入文件，便于持久化或后续导入数据库。"""

    def __init__(self, cfg: FileReportStoreNotifierConfig):
        self._path = Path(cfg.path)

    async def send_markdown(self, *, title: str, markdown: str) -> None:
        self._path.parent.mkdir(parents=True, exist_ok=True)
        with open(self._path, "a", encoding="utf-8") as f:
            f.write("\n---\n")
            f.write(f"# {title}\n\n")
            f.write(markdown)
            f.write("\n")

