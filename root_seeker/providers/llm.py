from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass
from typing import Any, Protocol

import httpx

logger = logging.getLogger(__name__)

# 超时等可重试异常，自动重试次数
_LLM_RETRY_MAX_ATTEMPTS = 2
_LLM_RETRY_DELAY_SECONDS = 2.0


class LLMProvider(Protocol):
    async def generate(self, *, system: str, user: str) -> str: ...
    
    async def generate_multi_turn(
        self, *, system: str, messages: list[dict[str, str]]
    ) -> str:
        """
        多轮对话接口
        
        Args:
            system: System prompt
            messages: 对话历史，格式为 [{"role": "user", "content": "..."}, {"role": "assistant", "content": "..."}, ...]
        
        Returns:
            LLM 返回的文本内容
        """
        ...


@dataclass(frozen=True)
class OpenAICompatConfig:
    base_url: str
    api_key: str
    model: str
    timeout_seconds: float = 60.0
    chat_url: str | None = None
    temperature: float = 0.2
    max_tokens: int | None = None


class OpenAICompatLLM:
    def __init__(self, cfg: OpenAICompatConfig, client: httpx.AsyncClient | None = None):
        self._cfg = cfg
        self._client = client or httpx.AsyncClient(timeout=cfg.timeout_seconds)

    async def generate(self, *, system: str, user: str) -> str:
        logger.debug(f"[LLM] 单轮对话请求，model={self._cfg.model}, user长度={len(user)}")
        url = (
            self._cfg.chat_url.rstrip("/")
            if self._cfg.chat_url
            else f"{self._cfg.base_url.rstrip('/')}/v1/chat/completions"
        )
        payload: dict[str, Any] = {
            "model": self._cfg.model,
            "messages": [
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            ],
            "temperature": self._cfg.temperature,
        }
        if self._cfg.max_tokens is not None:
            payload["max_tokens"] = self._cfg.max_tokens
        headers = {"Authorization": f"Bearer {self._cfg.api_key}"}
        last_err: Exception | None = None
        for attempt in range(_LLM_RETRY_MAX_ATTEMPTS):
            try:
                resp = await self._client.post(url, json=payload, headers=headers)
                resp.raise_for_status()
                data = resp.json()
                choices = data.get("choices") or []
                if not choices:
                    logger.error("[LLM] 响应中没有 choices")
                    raise RuntimeError("LLM response has no choices.")
                msg = choices[0].get("message") or {}
                content = msg.get("content")
                if not isinstance(content, str):
                    logger.error("[LLM] 响应内容不是字符串")
                    raise RuntimeError("LLM response content is not a string.")
                logger.debug(f"[LLM] 单轮对话完成，响应长度={len(content)}")
                return content
            except (httpx.ReadTimeout, httpx.ConnectTimeout, asyncio.TimeoutError) as e:
                last_err = e
                if attempt < _LLM_RETRY_MAX_ATTEMPTS - 1:
                    logger.warning(f"[LLM] 单轮对话超时/连接失败，{_LLM_RETRY_DELAY_SECONDS}秒后重试 ({attempt + 1}/{_LLM_RETRY_MAX_ATTEMPTS})：{e}")
                    await asyncio.sleep(_LLM_RETRY_DELAY_SECONDS)
                else:
                    logger.error(f"[LLM] 单轮对话失败（已重试{_LLM_RETRY_MAX_ATTEMPTS}次）：{e}", exc_info=True)
                    raise
            except Exception as e:
                logger.error(f"[LLM] 单轮对话失败：{e}", exc_info=True)
                raise
        raise last_err or RuntimeError("LLM single turn failed")

    async def generate_multi_turn(
        self, *, system: str, messages: list[dict[str, str]]
    ) -> str:
        """
        多轮对话：支持对话历史
        
        Args:
            system: System prompt
            messages: 对话历史，格式为 [{"role": "user", "content": "..."}, {"role": "assistant", "content": "..."}, ...]
        
        Returns:
            LLM 返回的文本内容
        """
        logger.debug(f"[LLM] 多轮对话请求，model={self._cfg.model}, 消息数={len(messages)}")
        url = (
            self._cfg.chat_url.rstrip("/")
            if self._cfg.chat_url
            else f"{self._cfg.base_url.rstrip('/')}/v1/chat/completions"
        )
        # 构建完整的 messages 数组（system + 对话历史）
        full_messages: list[dict[str, Any]] = [{"role": "system", "content": system}]
        full_messages.extend(messages)
        
        payload: dict[str, Any] = {
            "model": self._cfg.model,
            "messages": full_messages,
            "temperature": self._cfg.temperature,
        }
        if self._cfg.max_tokens is not None:
            payload["max_tokens"] = self._cfg.max_tokens
        headers = {"Authorization": f"Bearer {self._cfg.api_key}"}
        last_err: Exception | None = None
        for attempt in range(_LLM_RETRY_MAX_ATTEMPTS):
            try:
                resp = await self._client.post(url, json=payload, headers=headers)
                resp.raise_for_status()
                data = resp.json()
                choices = data.get("choices") or []
                if not choices:
                    logger.error("[LLM] 多轮对话响应中没有 choices")
                    raise RuntimeError("LLM response has no choices.")
                msg = choices[0].get("message") or {}
                content = msg.get("content")
                if not isinstance(content, str):
                    logger.error("[LLM] 多轮对话响应内容不是字符串")
                    raise RuntimeError("LLM response content is not a string.")
                logger.debug(f"[LLM] 多轮对话完成，响应长度={len(content)}")
                return content
            except (httpx.ReadTimeout, httpx.ConnectTimeout, asyncio.TimeoutError) as e:
                last_err = e
                if attempt < _LLM_RETRY_MAX_ATTEMPTS - 1:
                    logger.warning(f"[LLM] 多轮对话超时/连接失败，{_LLM_RETRY_DELAY_SECONDS}秒后重试 ({attempt + 1}/{_LLM_RETRY_MAX_ATTEMPTS})：{e}")
                    await asyncio.sleep(_LLM_RETRY_DELAY_SECONDS)
                else:
                    logger.error(f"[LLM] 多轮对话失败（已重试{_LLM_RETRY_MAX_ATTEMPTS}次）：{e}", exc_info=True)
                    raise
            except Exception as e:
                logger.error(f"[LLM] 多轮对话失败：{e}", exc_info=True)
                raise
        raise last_err or RuntimeError("LLM multi-turn failed")

    async def aclose(self) -> None:
        await self._client.aclose()

