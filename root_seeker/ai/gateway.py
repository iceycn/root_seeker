"""AiGateway：多 Provider 管理、动态配置切换。"""

from __future__ import annotations

import logging
import os
from typing import Any

from root_seeker.config import AiGatewayConfig, AiProviderConfig, AppConfig
from root_seeker.providers.llm import LLMProvider, OpenAICompatConfig, OpenAICompatLLM

logger = logging.getLogger(__name__)


def create_ai_gateway_from_app_config(cfg: AppConfig) -> AiGateway | None:
    """
    从 AppConfig 创建 AiGateway。
    若 cfg.ai.providers 非空则使用；否则从 cfg.llm 构建 main provider（兼容旧配置）。
    """
    if cfg.ai.providers:
        return AiGateway(cfg.ai)
    if cfg.llm is not None and cfg.llm.api_key:
        merged = AiGatewayConfig(
            default_provider="main",
            providers={
                "main": AiProviderConfig(
                    kind="openai",
                    api_key=cfg.llm.api_key,
                    base_url=str(cfg.llm.base_url),
                    model=cfg.llm.model,
                    timeout=int(cfg.llm.timeout_seconds),
                    temperature=cfg.llm.temperature,
                    max_tokens=cfg.llm.max_tokens,
                ),
            },
        )
        return AiGateway(merged)
    return None


def _resolve_api_key(raw: str) -> str:
    """解析 api_key：支持 ENV:VAR_NAME 引用环境变量。"""
    if not raw or not isinstance(raw, str):
        return raw or ""
    s = raw.strip()
    if s.upper().startswith("ENV:"):
        var_name = s[4:].strip()
        return os.environ.get(var_name, "")
    return s


def _provider_config_to_openai_compat(p: AiProviderConfig) -> OpenAICompatConfig:
    base_url = p.base_url or "https://api.openai.com/v1"
    if base_url.endswith("/v1") or base_url.endswith("/v1/"):
        chat_url = None
    else:
        chat_url = f"{base_url.rstrip('/')}/v1/chat/completions"
    return OpenAICompatConfig(
        base_url=base_url,
        api_key=_resolve_api_key(p.api_key),
        model=p.model,
        timeout_seconds=float(p.timeout),
        chat_url=chat_url,
        temperature=p.temperature,
        max_tokens=p.max_tokens,
    )


class AiGateway:
    """AI 网关：统一接口，支持多 Provider、动态切换与新增。"""

    def __init__(self, config: AiGatewayConfig):
        self._config = config
        self._providers: dict[str, LLMProvider] = {}
        self._extra_providers: dict[str, LLMProvider] = {}
        self._build_providers()

    def _build_providers(self) -> None:
        for name, pcfg in self._config.providers.items():
            if not pcfg or not pcfg.model:
                continue
            key = _resolve_api_key(pcfg.api_key)
            if not key:
                logger.warning(f"[AiGateway] Provider {name} 未配置有效 api_key，已跳过")
                continue
            try:
                compat = _provider_config_to_openai_compat(pcfg)
                self._providers[name] = OpenAICompatLLM(compat)
                logger.info(f"[AiGateway] 已加载 Provider: {name}")
            except Exception as e:
                logger.warning(f"[AiGateway] 加载 Provider {name} 失败: {e}")

    def get_provider(self, name: str | None = None) -> LLMProvider | None:
        """获取指定或默认的 LLM Provider。指定 name 不存在时回退到 default_provider。"""
        n = name or self._config.default_provider
        p = self._providers.get(n) or self._extra_providers.get(n)
        if p is not None:
            return p
        if name and name != self._config.default_provider:
            logger.warning(f"[AiGateway] Provider {name} 不存在，回退到 default={self._config.default_provider}")
            return self._providers.get(self._config.default_provider) or self._extra_providers.get(
                self._config.default_provider
            )
        return None

    async def chat_completion(
        self,
        messages: list[dict[str, str]],
        config_name: str | None = None,
        timeout: float | None = None,
        **kwargs: Any,
    ) -> str:
        """
        统一调用接口。
        messages: [{"role": "user", "content": "..."}, ...]
        返回 assistant 的 content。
        """
        provider = self.get_provider(config_name)
        if provider is None:
            raise RuntimeError(
                f"未找到 AI Provider: {config_name or self._config.default_provider}，请检查配置"
            )
        system = ""
        for m in messages:
            if isinstance(m, dict) and (m.get("role") or "").lower() == "system":
                system = (m.get("content") or "") + "\n" + system
        msgs = [m for m in messages if isinstance(m, dict) and (m.get("role") or "").lower() != "system"]
        if len(msgs) <= 1 and all((m.get("role") or "").lower() == "user" for m in msgs):
            user = msgs[0].get("content", "") if msgs else ""
            return await provider.generate(system=system or "You are a helpful assistant.", user=user)
        return await provider.generate_multi_turn(system=system or "You are a helpful assistant.", messages=msgs)

    def add_provider(self, name: str, config: AiProviderConfig) -> None:
        """动态新增配置。"""
        key = _resolve_api_key(config.api_key)
        if not key:
            logger.warning(f"[AiGateway] 新增 Provider {name} 未配置有效 api_key")
            return
        try:
            compat = _provider_config_to_openai_compat(config)
            self._extra_providers[name] = OpenAICompatLLM(compat)
            logger.info(f"[AiGateway] 已动态新增 Provider: {name}")
        except Exception as e:
            logger.warning(f"[AiGateway] 动态新增 Provider {name} 失败: {e}")
