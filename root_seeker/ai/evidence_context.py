"""EvidenceContext：分析过程中收集到的证据上下文，供 evidence.context_search 工具查询。"""

from __future__ import annotations

import hashlib
import json
import re
from typing import Any

from root_seeker.ai.token_budget import count_tokens


def _content_ref(content: str, tool_name: str, key_hint: str) -> str:
    """从内容提取简短引用（file_path、hits 等）。"""
    if not content:
        return f"{tool_name}: (空)"
    try:
        data = json.loads(content)
        if isinstance(data, dict):
            if "file_path" in data:
                return f"{tool_name}: file_path={data.get('file_path', '')}"
            if "hits" in data and data["hits"]:
                first = data["hits"][0] if isinstance(data["hits"], list) else {}
                fp = first.get("file_path", first.get("file_path", "")) if isinstance(first, dict) else ""
                return f"{tool_name}: hits[0]={fp}"
            if "locations" in data and data["locations"]:
                first = data["locations"][0] if isinstance(data["locations"], list) else {}
                fp = first.get("file_path", "") if isinstance(first, dict) else ""
                return f"{tool_name}: locations[0]={fp}"
    except (json.JSONDecodeError, TypeError):
        pass
    return f"{tool_name}: {content[:80]}..." if len(content) > 80 else f"{tool_name}: {content}"


def extract_keywords(text: str) -> set[str]:
    """从文本提取可检索关键词（类名、方法名、配置项等，至少 2 字符）。"""
    if not text or not isinstance(text, str):
        return set()
    words = re.findall(r"[A-Za-z_][A-Za-z0-9_]{1,50}", text)
    return {w for w in words if len(w) >= 2}


def _relevance_score(content: str, keywords: set[str]) -> int:
    """计算内容与相关性关键词的匹配数。关键词越多匹配，分数越高。"""
    if not keywords or not content:
        return 0
    lower = content.lower()
    return sum(1 for kw in keywords if kw and kw.lower() in lower)


class EvidenceContext:
    """
    分析过程中收集到的证据上下文。由 AI 通过 evidence.context_search 工具规划查找。
    v3.0.0：压缩时保留首次定位证据 + 高相关性证据 + 最近证据；支持 token 预算。
    """

    def __init__(
        self,
        max_total_chars: int = 80_000,
        max_total_tokens: int | None = None,
        relevance_keywords: set[str] | None = None,
    ):
        self._entries: list[tuple[str, str, str, bool]] = []  # (tool_name, key_hint, content, is_first_locator)
        self._max_total_chars = max_total_chars
        self._max_total_tokens = max_total_tokens or (max_total_chars // 2)  # 字符/2 近似 token
        self._relevance_keywords = relevance_keywords or set()
        self._total_chars = 0
        self._total_tokens = 0
        self._round_summary_index: dict[str, str] = {}  # hash -> ref，v3.0.0 轮次摘要索引

    def set_relevance_keywords(self, keywords: set[str]) -> None:
        """设置相关性关键词，供压缩时优先保留高相关证据。"""
        self._relevance_keywords = keywords or set()

    def add(self, tool_name: str, content: str, key_hint: str = "", is_first_locator: bool = False) -> None:
        if not content:
            return
        remaining_chars = self._max_total_chars - self._total_chars - 100
        if remaining_chars <= 0:
            return
        content = content[:remaining_chars]
        if not content:
            return
        self._entries.append((tool_name, key_hint, content, is_first_locator))
        self._total_chars += len(content)
        self._total_tokens += count_tokens(content)
        if self._total_chars > self._max_total_chars or self._total_tokens > self._max_total_tokens:
            self._evict_middle()

    def _evict_middle(self) -> None:
        """相关性保留压缩：保留首次定位证据 + 高相关性证据 + 最近证据；超 token/字符预算时 evict 中间低相关项。"""
        if len(self._entries) <= 8:
            return
        if self._total_chars <= self._max_total_chars and self._total_tokens <= self._max_total_tokens:
            return
        keep_first, keep_last = 3, 5
        if len(self._entries) <= keep_first + keep_last:
            return
        # 中间段：按相关性排序，低相关先 evict；构建保留列表避免 pop 索引错位
        middle_start, middle_end = keep_first, len(self._entries) - keep_last
        middle_items = [
            (i, self._entries[i], _relevance_score(self._entries[i][2], self._relevance_keywords))
            for i in range(middle_start, middle_end)
        ]
        # 低相关先 evict：排序使 evict 顺序为 (非 first_locator 优先, 低分优先)
        middle_items.sort(key=lambda x: (0 if x[1][3] else 1, x[2], x[0]))
        kept_middle: list[tuple[str, str, str, bool]] = []
        dropped_chars, dropped_tokens = 0, 0
        need_drop_chars = max(0, self._total_chars - self._max_total_chars)
        need_drop_tokens = max(0, self._total_tokens - self._max_total_tokens)
        for _idx, item, _score in middle_items:
            content = item[2]
            c_len, c_tok = len(content), count_tokens(content)
            if dropped_chars >= need_drop_chars and dropped_tokens >= need_drop_tokens:
                kept_middle.append(item)
            else:
                tool_name, key_hint, _, _ = item
                h = hashlib.md5(content.encode("utf-8", errors="replace")).hexdigest()[:12]
                self._round_summary_index[h] = _content_ref(content, tool_name, key_hint)
                dropped_chars += c_len
                dropped_tokens += c_tok
        self._entries = self._entries[:keep_first] + kept_middle + self._entries[-keep_last:]
        self._total_chars -= dropped_chars
        self._total_tokens -= dropped_tokens

    def search(self, query: str) -> dict[str, Any]:
        """
        根据查询在上下文中搜索。返回 JSON 格式：{"found": bool, "matches": [...], "total_entries": int}。
        由 AI 通过 evidence.context_search 工具调用。
        """
        keywords = extract_keywords(query)
        matches: list[dict[str, Any]] = []
        for tool_name, key_hint, content, _ in self._entries:
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
        out: dict[str, Any] = {
            "found": len(matches) > 0,
            "match_count": len(matches),
            "total_entries": len(self._entries),
            "matches": matches,
        }
        if self._round_summary_index:
            out["round_summary_index"] = self._round_summary_index
        return out

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
        """从已有 tool_results 初始化上下文。首个 code.search/evidence 结果标记为 first_locator。"""
        first_locator_tools = ("code.search", "evidence.context_search")
        seen_first = False
        for name, text, *_ in tool_results:
            if name and text and name != "evidence.context_search":
                is_first = not seen_first and name in first_locator_tools
                if is_first:
                    seen_first = True
                self.add(name, text, is_first_locator=is_first)
