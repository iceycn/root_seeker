"""AI 网关测试：chat_completion、get_provider、add_provider、ENV 解析、向后兼容。"""

from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from root_seeker.ai.gateway import AiGateway, create_ai_gateway_from_app_config
from root_seeker.config import (
    AiGatewayConfig,
    AiProviderConfig,
    AliyunSlsConfig,
    AppConfig,
    LlmProviderConfig,
)


@pytest.fixture
def gateway_with_mock():
    """创建带 Mock LLM 的 AiGateway。"""
    cfg = AiGatewayConfig(
        default_provider="main",
        providers={
            "main": AiProviderConfig(
                kind="openai",
                api_key="test-key",
                base_url="https://api.example.com",
                model="gpt-4",
            ),
        },
    )
    gw = AiGateway(cfg)
    mock_llm = AsyncMock()
    mock_llm.generate = AsyncMock(return_value="ok")
    mock_llm.generate_multi_turn = AsyncMock(return_value="ok")
    gw._providers["main"] = mock_llm
    return gw


def test_chat_completion_normal(gateway_with_mock):
    """TC-AI-001: chat_completion 正常调用。"""
    result = asyncio.run(
        gateway_with_mock.chat_completion(messages=[{"role": "user", "content": "hi"}])
    )
    assert result == "ok"
    gateway_with_mock._providers["main"].generate.assert_called_once()


def test_get_provider_returns_config(gateway_with_mock):
    """TC-AI-002: get_provider 返回配置。"""
    p = gateway_with_mock.get_provider("main")
    assert p is not None
    p = gateway_with_mock.get_provider()
    assert p is not None


def test_add_provider_dynamic(gateway_with_mock):
    """TC-AI-003: add_provider 动态新增。"""
    gateway_with_mock.add_provider(
        "extra",
        AiProviderConfig(
            kind="openai",
            api_key="extra-key",
            model="gpt-3.5",
        ),
    )
    p = gateway_with_mock.get_provider("extra")
    assert p is not None


def test_env_prefix_resolution():
    """TC-AI-004: ENV: 前缀解析。"""
    import os

    os.environ["TEST_AI_KEY"] = "secret123"
    try:
        cfg = AiGatewayConfig(
            default_provider="main",
            providers={
                "main": AiProviderConfig(
                    kind="openai",
                    api_key="ENV:TEST_AI_KEY",
                    model="gpt-4",
                ),
            },
        )
        gw = AiGateway(cfg)
        # 验证 provider 已加载（api_key 解析成功）
        p = gw.get_provider("main")
        assert p is not None
    finally:
        os.environ.pop("TEST_AI_KEY", None)


def test_provider_not_found_fallback(gateway_with_mock):
    """TC-AI-005: 指定 provider 不存在时回退 default。"""
    p = gateway_with_mock.get_provider("nonexistent")
    # 应回退到 main
    assert p is not None
    assert p == gateway_with_mock.get_provider("main")


def test_create_ai_gateway_from_app_config_llm_fallback():
    """TC-AI-006: create_ai_gateway_from_app_config 兼容 cfg.llm。"""
    cfg = AppConfig(
        aliyun_sls=AliyunSlsConfig(
            endpoint="https://cn-hangzhou.log.aliyuncs.com",
            access_key_id="test",
            access_key_secret="test",
            project="test",
            logstore="test",
        ),
        sql_templates=[],
        llm=LlmProviderConfig(
            api_key="llm-key",
            base_url="https://llm.example.com",
            model="gpt-4",
        ),
        ai=AiGatewayConfig(providers={}),
    )
    gw = create_ai_gateway_from_app_config(cfg)
    assert gw is not None
    p = gw.get_provider("main")
    assert p is not None
