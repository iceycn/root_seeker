"""上下文发现模块：从错误日志解析引用，预取上下文。

- 从 error_log 提取可检索的「引用」：trace_id、类名、方法名、配置项、接口路径
- 预取结构化上下文：index 概览、correlation 概览（若有 trace_id）
- 供 Plan 阶段注入，减少 AI 盲目猜测
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any  # noqa: F401 - used in type hints


@dataclass
class DiscoveredContext:
    """发现的结构化上下文，供 Plan 注入。"""

    index_preview: str
    correlation_preview: str
    extracted_refs: dict[str, list[str]]
    hints_for_plan: str


def extract_trace_id(text: str) -> str | None:
    """从错误日志提取 trace_id。"""
    if not text or not isinstance(text, str):
        return None
    patterns = [
        r"trace_id[:=]\s*([a-zA-Z0-9_-]{12,})",
        r"traceId[:=]\s*([a-zA-Z0-9_-]{12,})",
        r"\[trace_id:\s*([a-zA-Z0-9_-]{12,})\]",
        r'"trace_id"\s*:\s*"([a-zA-Z0-9_-]{12,})"',
        r'"traceId"\s*:\s*"([a-zA-Z0-9_-]{12,})"',
    ]
    for p in patterns:
        m = re.search(p, text, re.IGNORECASE)
        if m:
            return m.group(1).strip()
    return None


def extract_request_id(text: str) -> str | None:
    """从错误日志提取 request_id。"""
    if not text or not isinstance(text, str):
        return None
    patterns = [
        r"request_id[:=]\s*([a-zA-Z0-9_-]{12,})",
        r"requestId[:=]\s*([a-zA-Z0-9_-]{12,})",
        r'"request_id"\s*:\s*"([a-zA-Z0-9_-]{12,})"',
    ]
    for p in patterns:
        m = re.search(p, text, re.IGNORECASE)
        if m:
            return m.group(1).strip()
    return None


def extract_class_method_names(text: str, max_items: int = 12) -> list[str]:
    """从堆栈/日志提取类名、方法名（Java/Python/Go 常见格式）。"""
    if not text or not isinstance(text, str):
        return []
    seen: set[str] = set()
    result: list[str] = []

    # Java: at com.foo.Bar.baz(Bar.java:123)
    for m in re.finditer(r"at\s+([A-Za-z0-9_.]+)\.([a-zA-Z0-9_]+)\s*\(", text):
        cls, method = m.group(1), m.group(2)
        key = f"{cls}.{method}"
        if key not in seen and len(result) < max_items:
            seen.add(key)
            result.append(key)

    # Python: File "foo/bar.py", line 10, in baz
    for m in re.finditer(r'in\s+([a-zA-Z0-9_]+)\s*$', text, re.MULTILINE):
        fn = m.group(1)
        if fn not in seen and fn not in ("<module>",) and len(result) < max_items:
            seen.add(fn)
            result.append(fn)

    # 通用：驼峰类名、常见方法名
    for m in re.finditer(r"\b([A-Z][a-zA-Z0-9]*(?:Service|Controller|Handler|Manager|Client|Config))\b", text):
        name = m.group(1)
        if name not in seen and len(result) < max_items:
            seen.add(name)
            result.append(name)

    return result[:max_items]


def extract_config_keys(text: str, max_items: int = 8) -> list[str]:
    """从日志提取可能的配置项、URL、接口路径。"""
    if not text or not isinstance(text, str):
        return []
    seen: set[str] = set()
    result: list[str] = []

    # key=value, "key": "value"
    for m in re.finditer(r'["\']?([a-zA-Z_][a-zA-Z0-9_.]*(?:url|path|key|config|endpoint))["\']?\s*[:=]', text, re.IGNORECASE):
        key = m.group(1)
        if key not in seen and len(result) < max_items:
            seen.add(key)
            result.append(key)

    # /api/xxx 路径
    for m in re.finditer(r"(/[\w/-]+(?:/v\d+)?)", text):
        path = m.group(1)
        if len(path) > 4 and path not in seen and len(result) < max_items:
            seen.add(path)
            result.append(path)

    return result[:max_items]


def extract_error_codes(text: str, max_items: int = 5) -> list[str]:
    """从日志提取 error_code、错误码。"""
    if not text or not isinstance(text, str):
        return []
    seen: set[str] = set()
    result: list[str] = []

    for m in re.finditer(r'"error_code"\s*:\s*"([^"]+)"', text):
        code = m.group(1)
        if code not in seen and len(result) < max_items:
            seen.add(code)
            result.append(code)
    for m in re.finditer(r"error_code[:=]\s*([a-zA-Z0-9_]+)", text, re.IGNORECASE):
        code = m.group(1)
        if code not in seen and len(result) < max_items:
            seen.add(code)
            result.append(code)
    return result[:max_items]


# 关键行模式：优先采样包含这些模式的日志行，避免截断漏检 trace_id/堆栈
_KEY_LINE_PATTERNS = (
    "trace_id", "traceId", "trace_id:", "traceId:",
    "stacktrace", "Stack trace", "Exception", "Error",
    "at com.", "at org.", "at java.", "at sun.",
    "File \"", "in <module>", "Caused by:",
)

def _prioritize_key_lines(text: str, max_chars: int) -> tuple[str, bool, int]:
    """抽样窗口 + 关键行优先：先收集含关键信号的行，再补其余，避免截断漏检。"""
    if not text or len(text) <= max_chars:
        return text or "", False, len(text or "")
    lines = text.splitlines()
    key_lines: list[str] = []
    rest_lines: list[str] = []
    for line in lines:
        lower = line.lower()
        if any(p.lower() in lower for p in _KEY_LINE_PATTERNS):
            key_lines.append(line)
        else:
            rest_lines.append(line)
    combined = "\n".join(key_lines + rest_lines)
    truncated = len(combined) > max_chars
    preview = combined[:max_chars]
    return preview, truncated, len(text)


def discover_refs_from_error_log(error_log: str, max_preview_chars: int = 4000) -> dict[str, list[str] | Any]:
    """从 error_log 发现可检索的引用。采用关键行优先采样，避免截断漏检 trace_id/堆栈。"""
    full = error_log or ""
    preview, was_truncated, original_len = _prioritize_key_lines(full, max_preview_chars)
    refs: dict[str, list[str] | Any] = {}

    trace_id = extract_trace_id(preview)
    if trace_id:
        refs["trace_id"] = [trace_id]

    request_id = extract_request_id(preview)
    if request_id:
        refs["request_id"] = [request_id]

    classes = extract_class_method_names(preview)
    if classes:
        refs["class_method"] = classes

    configs = extract_config_keys(preview)
    if configs:
        refs["config_key"] = configs

    codes = extract_error_codes(preview)
    if codes:
        refs["error_code"] = codes

    if was_truncated:
        refs["_discovery_meta"] = {
            "truncated": True,
            "original_length": original_len,
            "preview_length": len(preview),
            "hint": "日志已截断采样，trace_id/堆栈等可能在后文，Plan 可考虑 correlation.get_info 补全",
        }
    return refs


def extract_relevance_keywords(error_log: str, max_keywords: int = 25) -> set[str]:
    """
    从 error_log 提取相关性关键词，供证据压缩时优先保留与错误签名、trace_id、目标符号直接相关的证据。
    返回可用于匹配证据内容的关键词集合。
    """
    if not error_log or not isinstance(error_log, str):
        return set()
    refs = discover_refs_from_error_log(error_log, max_preview_chars=6000)
    keywords: set[str] = set()
    for key in ("trace_id", "request_id"):
        vals = refs.get(key)
        if isinstance(vals, list):
            keywords.update(str(v).strip() for v in vals if v and len(str(v).strip()) >= 4)
    for key in ("class_method", "config_key", "error_code"):
        vals = refs.get(key)
        if isinstance(vals, list):
            keywords.update(str(v).strip() for v in vals[:8] if v and len(str(v).strip()) >= 2)
    # 错误类型：Exception 名、ClassNotFound 等
    for m in re.finditer(r"\b([A-Za-z][A-Za-z0-9_]*(?:Exception|Error|NotFound|Timeout))\b", error_log):
        keywords.add(m.group(1))
    filtered = [k for k in keywords if k and len(k) >= 2]
    return set(filtered[:max_keywords])


def build_hints_for_plan(refs: dict[str, list[str] | Any]) -> str:
    """根据发现的引用生成 Plan 提示。"""
    lines: list[str] = []
    if refs.get("trace_id"):
        lines.append(f"- 已发现 trace_id，可调用 correlation.get_info 获取调用链日志")
    if refs.get("class_method"):
        cm = refs["class_method"][:5]
        lines.append(f"- 已发现类/方法: {', '.join(cm)}，可优先 code.search/evidence.context_search 定位")
    if refs.get("config_key"):
        ck = refs["config_key"][:3]
        lines.append(f"- 已发现配置/路径: {', '.join(ck)}，检索时可作为关键词")
    if refs.get("error_code"):
        ec = refs["error_code"][:3]
        lines.append(f"- 已发现 error_code: {', '.join(ec)}，分析时需结合业务逻辑")
    meta = refs.get("_discovery_meta")
    if isinstance(meta, dict) and meta.get("truncated"):
        lines.append(f"- 【截断提示】日志已采样（原长 {meta.get('original_length', 0)} 字），未发现 trace_id 时建议 correlation.get_info 补全")
    if not lines:
        return "（未从日志中提取到结构化引用，建议先 index.get_status 了解仓库结构）"
    return "\n".join(lines)
