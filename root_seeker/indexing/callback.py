"""索引任务回调：任务完成后 POST 到 callback_url，供 Admin 更新 repo_index_status。"""
from __future__ import annotations

import asyncio
import logging
from typing import Any
from urllib.parse import unquote

logger = logging.getLogger(__name__)


async def fire_callback(url: str, payload: dict[str, Any]) -> None:
    """异步 POST 回调，不阻塞。若 url 为空则不执行。"""
    if not url or not url.strip():
        return
    logger.info(
        "[IndexCallback] 准备发送回调 url=%s service_name=%s task_type=%s status=%s",
        url,
        payload.get("service_name"),
        payload.get("task_type"),
        payload.get("status"),
    )
    # callback_url 可能被 URL 编码（如 http%3A%2F%2F...），需解码后 httpx 才能识别协议
    raw = url.strip()
    if not raw.startswith(("http://", "https://")):
        raw = unquote(raw)
    try:
        import httpx
        async with httpx.AsyncClient(timeout=10.0) as client:
            r = await client.post(raw, json=payload)
            if r.status_code >= 400:
                logger.warning("[IndexCallback] 回调失败 url=%s status=%s body=%s", url, r.status_code, r.text[:200] if r.text else "")
            else:
                logger.info("[IndexCallback] 回调成功 url=%s service=%s task_type=%s", url, payload.get("service_name"), payload.get("task_type"))
    except Exception as e:
        logger.warning("[IndexCallback] 回调异常 url=%s: %s", url, e)
