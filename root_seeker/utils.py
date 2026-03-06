from __future__ import annotations

import json
import logging
import re
from typing import Any

logger = logging.getLogger(__name__)

try:
    import tiktoken
except ImportError:
    tiktoken = None

def count_tokens(text: str, model: str = "gpt-4") -> int:
    """
    Count the number of tokens in a string.
    If tiktoken is not available, returns an approximation (len / 4).
    """
    if not text:
        return 0
    if tiktoken:
        try:
            encoding = tiktoken.encoding_for_model(model)
            return len(encoding.encode(text))
        except Exception:
            # Fallback for unknown models or errors
            try:
                encoding = tiktoken.get_encoding("cl100k_base")
                return len(encoding.encode(text))
            except Exception:
                pass
    
    # Fallback approximation: 1 token ~= 4 chars in English, but for Chinese it's more like 1 char = 1-2 tokens.
    # Safe estimate: len(text) / 2 for mixed content, or just len(text) to be super safe if we care about limits.
    # Common rule of thumb: 1 token ~= 4 chars.
    return len(text) // 4

def parse_json_markdown(text: str) -> Any:
    """
    Parse a JSON string that might be wrapped in markdown code blocks.
    """
    if not text:
        return {}

    text = text.strip()
    
    # Try to parse directly
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        pass

    # Try to find JSON block in markdown
    match = re.search(r"```(?:json)?\s*(\{.*?\})\s*```", text, re.DOTALL)
    if match:
        try:
            return json.loads(match.group(1))
        except json.JSONDecodeError:
            pass

    # Try to find just the first brace pair
    match = re.search(r"(\{.*\})", text, re.DOTALL)
    if match:
        try:
            return json.loads(match.group(1))
        except json.JSONDecodeError:
            pass
            
    # Try to repair common errors (very basic)
    # e.g. replacing ' with "
    try:
        fixed_text = text.replace("'", '"')
        return json.loads(fixed_text)
    except json.JSONDecodeError:
        pass

    logger.warning(f"Failed to parse JSON from text: {text[:100]}...")
    return {}
