"""EvidenceContext：分析过程中收集到的证据上下文，供 evidence.context_search 工具查询。"""

from __future__ import annotations

import json
import re
from typing import Any


def extract_keywords(text: str) -> set[str]:
    """从文本提取可检索关键词（类名、方法名、配置项等，至少 2 字符）。"""
    if not text or not isinstance(text, str):
        return set()
    words = re.findall(r"[A-Za-z_][A-Za-z0-9_]{1,50}", text)
    return {w for w in words if len(w) >= 2}


class EvidenceContext:
    """
    分析过程中收集到的证据上下文。由 AI 通过 evidence.context_search 工具规划查找。
    """

    def __init__(self, max_total_chars: int = 80_000):
        self._entries: list[tuple[str, str, str]] = []
        self._max_total_chars = max_total_chars
        self._total_chars = 0

    def add(self, tool_name: str, content: str, key_hint: str = "") -> None:
        if not content or self._total_chars >= self._max_total_chars:
            return
        content = content[: self._max_total_chars - self._total_chars - 100]
        self._entries.append((tool_name, key_hint, content))
        self._total_chars += len(content)

    def search(self, query: str) -> dict[str, Any]:
        """
        根据查询在上下文中搜索。返回 JSON 格式：{"found": bool, "matches": [...], "total_entries": int}。
        由 AI 通过 evidence.context_search 工具调用。
        """
        keywords = extract_keywords(query)
        matches: list[dict[str, Any]] = []
        for tool_name, key_hint, content in self._entries:
            if not content:
                continue
            if keywords and any(kw.lower() in content.lower() for kw in keywords):
                matches.append({
                    "source": tool_name,
                    "key_hint": key_hint,
                    "content_preview": content[:2000] + ("..." if len(content) > 2000 else ""),
                })
            elif not keywords and query.strip() and query.strip().lower() in content.lower():
                matches.append({
                    "source": tool_name,
                    "key_hint": key_hint,
                    "content_preview": content[:2000] + ("..." if len(content) > 2000 else ""),
                })
        return {
            "found": len(matches) > 0,
            "match_count": len(matches),
            "total_entries": len(self._entries),
            "matches": matches,
        }

    def to_evidence_text(self, query: str) -> str:
        """将搜索结果转为可注入 tool_results 的文本格式。"""
        result = self.search(query)
        if not result["found"]:
            return json.dumps(result, ensure_ascii=False)
        parts = []
        for m in result["matches"]:
            parts.append(f"[{m['source']}]\n{m['content_preview']}")
        return "\n\n---\n\n".join(parts)

    def from_tool_results(self, tool_results: list[tuple[str, str, bool, Any]]) -> None:
        """从已有 tool_results 初始化上下文。"""
        for name, text, *_ in tool_results:
            if name and text and name != "evidence.context_search":
                self.add(name, text)
