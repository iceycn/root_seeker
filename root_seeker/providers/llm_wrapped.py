from __future__ import annotations

import hashlib
import logging
import time
from dataclasses import dataclass
from typing import Any, Optional

from root_seeker.providers.llm import LLMProvider
from root_seeker.runtime.circuit_breaker import CircuitBreaker
from root_seeker.storage.audit_log import AuditLogger

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class LlmRuntimeConfig:
    concurrency: int = 4
    breaker_failure_threshold: int = 5
    breaker_reset_seconds: float = 30.0


class RateLimitedCircuitBreakerLLM:
    def __init__(
        self,
        *,
        inner: LLMProvider,
        cfg: LlmRuntimeConfig,
        audit: Optional[AuditLogger],
    ):
        import asyncio

        self._inner = inner
        self._sem = asyncio.Semaphore(cfg.concurrency)
        self._breaker = CircuitBreaker(
            failure_threshold=cfg.breaker_failure_threshold,
            reset_seconds=cfg.breaker_reset_seconds,
        )
        self._audit = audit

    async def generate(self, *, system: str, user: str) -> str:
        if not self._breaker.allow():
            logger.warning("[LLMWrapped] 熔断器已打开，拒绝请求")
            raise RuntimeError("llm circuit breaker open")

        user_hash = hashlib.sha256(user.encode("utf-8", errors="ignore")).hexdigest()
        t0 = time.time()
        logger.debug(f"[LLMWrapped] 单轮对话开始，user长度={len(user)}")
        async with self._sem:
            try:
                out = await self._inner.generate(system=system, user=user)
                elapsed_ms = int((time.time() - t0) * 1000)
                self._breaker.on_success()
                logger.info(f"[LLMWrapped] 单轮对话成功，耗时={elapsed_ms}ms, 响应长度={len(out)}")
                if self._audit:
                    self._audit.log(
                        {
                            "type": "llm_generate",
                            "status": "ok",
                            "user_hash": user_hash,
                            "user_chars": len(user),
                            "elapsed_ms": elapsed_ms,
                        }
                    )
                return out
            except Exception as e:
                elapsed_ms = int((time.time() - t0) * 1000)
                self._breaker.on_failure()
                logger.error(f"[LLMWrapped] 单轮对话失败，耗时={elapsed_ms}ms, 错误={e}", exc_info=True)
                if self._audit:
                    self._audit.log(
                        {
                            "type": "llm_generate",
                            "status": "error",
                            "user_hash": user_hash,
                            "user_chars": len(user),
                            "elapsed_ms": elapsed_ms,
                            "error": str(e),
                        }
                    )
                raise

    async def generate_multi_turn(self, *, system: str, messages: list[dict[str, str]]) -> str:
        """多轮对话：支持对话历史"""
        if not self._breaker.allow():
            logger.warning("[LLMWrapped] 熔断器已打开，拒绝多轮对话请求")
            raise RuntimeError("llm circuit breaker open")

        # 计算所有消息的总字符数用于审计
        total_chars = sum(len(msg.get("content", "")) for msg in messages)
        messages_hash = hashlib.sha256(
            "|".join(f"{m.get('role')}:{m.get('content', '')[:100]}" for m in messages).encode("utf-8", errors="ignore")
        ).hexdigest()
        t0 = time.time()
        logger.debug(f"[LLMWrapped] 多轮对话开始，消息数={len(messages)}, 总字符数={total_chars}")
        async with self._sem:
            try:
                out = await self._inner.generate_multi_turn(system=system, messages=messages)
                elapsed_ms = int((time.time() - t0) * 1000)
                self._breaker.on_success()
                logger.info(f"[LLMWrapped] 多轮对话成功，耗时={elapsed_ms}ms, 响应长度={len(out)}")
                if self._audit:
                    self._audit.log(
                        {
                            "type": "llm_generate_multi_turn",
                            "status": "ok",
                            "messages_hash": messages_hash,
                            "total_chars": total_chars,
                            "message_count": len(messages),
                            "elapsed_ms": elapsed_ms,
                        }
                    )
                return out
            except Exception as e:
                elapsed_ms = int((time.time() - t0) * 1000)
                self._breaker.on_failure()
                logger.error(f"[LLMWrapped] 多轮对话失败，耗时={elapsed_ms}ms, 错误={e}", exc_info=True)
                if self._audit:
                    self._audit.log(
                        {
                            "type": "llm_generate_multi_turn",
                            "status": "error",
                            "messages_hash": messages_hash,
                            "total_chars": total_chars,
                            "message_count": len(messages),
                            "elapsed_ms": elapsed_ms,
                            "error": str(e),
                        }
                    )
                raise

    async def generate_with_tools(
        self,
        *,
        system: str,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]],
    ) -> tuple[str | None, list[dict[str, Any]]]:
        """支持原生 tool calling（Cline/Cursor 风格），委托给 inner。"""
        if not hasattr(self._inner, "generate_with_tools"):
            return (None, [])
        if not self._breaker.allow():
            logger.warning("[LLMWrapped] 熔断器已打开，拒绝 tool calling 请求")
            raise RuntimeError("llm circuit breaker open")
        t0 = time.time()
        async with self._sem:
            try:
                content, tool_calls = await self._inner.generate_with_tools(
                    system=system, messages=messages, tools=tools
                )
                self._breaker.on_success()
                logger.info(
                    "[LLMWrapped] tool calling 成功，耗时=%dms, tool_calls=%d",
                    int((time.time() - t0) * 1000),
                    len(tool_calls),
                )
                return (content, tool_calls)
            except Exception as e:
                self._breaker.on_failure()
                logger.error("[LLMWrapped] tool calling 失败: %s", e, exc_info=True)
                raise

