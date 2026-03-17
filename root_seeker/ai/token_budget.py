"""Token 预算：基于 tiktoken 的 token 计数，供 EvidenceContext、Orchestrator 截断与压缩决策。"""

from __future__ import annotations

import logging
from typing import List

logger = logging.getLogger(__name__)

# 默认编码（cl100k_base 与 GPT-4 兼容），中文约 1.5~2 字符/token
_encoder = None


def _get_encoder():
    global _encoder
    if _encoder is None:
        try:
            import tiktoken
            _encoder = tiktoken.get_encoding("cl100k_base")
        except Exception as e:
            logger.debug("[TokenBudget] tiktoken 加载失败，回退到字符估算: %s", e)
            _encoder = None
    return _encoder


def count_tokens(text: str) -> int:
    """计算文本 token 数。tiktoken 不可用时用字符数/2 近似（中文偏多）。"""
    if not text:
        return 0
    enc = _get_encoder()
    if enc is not None:
        try:
            return len(enc.encode(text))
        except Exception:
            pass
    # 回退：字符数 / 2 作为近似（英文约 4 字符/token，中文约 1.5~2）
    return max(1, len(text) // 2)


def count_tokens_for_entries(entries: List[tuple]) -> int:
    """计算 entries 列表的总 token 数。entries 格式：(tool_name, key_hint, content, is_first_locator)。"""
    total = 0
    for _, _, content, _ in entries:
        total += count_tokens(content or "")
    return total
