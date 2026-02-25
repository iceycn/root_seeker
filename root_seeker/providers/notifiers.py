from __future__ import annotations

import base64
import hmac
import hashlib
import logging
import time
import urllib.parse
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
    secret: str | None = None
    security_mode: str = "ip"  # sign | keyword | ip


class WeComNotifier:
    def __init__(self, cfg: WeComNotifierConfig, client: httpx.AsyncClient | None = None):
        self._cfg = cfg
        self._client = client or httpx.AsyncClient(timeout=10.0)

    async def send_markdown(self, *, title: str, markdown: str) -> None:
        # sign 模式需加签；keyword、ip 模式直接使用 webhook URL（企微群机器人 key 已在 URL 中）
        url = str(self._cfg.webhook_url)
        if self._cfg.security_mode == "sign" and self._cfg.secret:
            url = _dingtalk_signed_url(url, self._cfg.secret)  # 企微加签算法与钉钉兼容
        payload = {
            "msgtype": "markdown",
            "markdown": {
                "content": f"### {title}\n{markdown}",
            },
        }
        resp = await self._client.post(url, json=payload)
        resp.raise_for_status()


@dataclass(frozen=True)
class DingTalkNotifierConfig:
    webhook_url: str
    secret: str | None = None
    security_mode: str = "sign"  # sign | keyword | ip


def _dingtalk_signed_url(webhook_url: str, secret: str) -> str:
    """钉钉加签：将 timestamp 和 sign 追加到 URL。参考 https://open.dingtalk.com/document/robots/customize-robot-security-settings"""
    timestamp = str(round(time.time() * 1000))
    string_to_sign = f"{timestamp}\n{secret}"
    hmac_code = hmac.new(
        secret.encode("utf-8"),
        string_to_sign.encode("utf-8"),
        digestmod=hashlib.sha256,
    ).digest()
    sign = urllib.parse.quote_plus(base64.b64encode(hmac_code).decode("utf-8"))
    sep = "&" if "?" in webhook_url else "?"
    return f"{webhook_url}{sep}timestamp={timestamp}&sign={sign}"


class DingTalkNotifier:
    def __init__(self, cfg: DingTalkNotifierConfig, client: httpx.AsyncClient | None = None):
        self._cfg = cfg
        self._client = client or httpx.AsyncClient(timeout=10.0)

    async def send_markdown(self, *, title: str, markdown: str) -> None:
        url = str(self._cfg.webhook_url)
        # sign 模式需加签；keyword、ip 模式直接使用 webhook URL
        if self._cfg.security_mode == "sign" and self._cfg.secret:
            url = _dingtalk_signed_url(url, self._cfg.secret)
        payload = {
            "msgtype": "markdown",
            "markdown": {
                "title": title,
                "text": markdown,
            },
        }
        resp = await self._client.post(url, json=payload)
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

