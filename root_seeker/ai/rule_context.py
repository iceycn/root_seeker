"""
规则上下文构建：从 tool_results 提取路径等。

从 tool_results 提取 file_path、repo_id 等路径信息，用于规则激活、Plan 提示。
"""

from __future__ import annotations

import json
import re
from typing import Any

MAX_RULE_PATH_CANDIDATES = 100


def extract_paths_from_tool_results(
    tool_results: list[tuple[str, str, bool, dict | None]],
) -> list[str]:
    """从 tool_results 提取路径（file_path、repo_id 等）。

    来源：
    - code.search 返回的 hits[].file_path
    - code.read 的 args.file_path
    - index.get_status 返回的 repos[].service_name（作为 repo 标识）
    """
    paths: list[str] = []
    seen: set[str] = set()

    for name, text, is_err, args in tool_results:
        if is_err:
            continue
        # code.read args
        if name == "code.read" and isinstance(args, dict):
            fp = args.get("file_path")
            if fp and isinstance(fp, str) and len(fp.strip()) >= 2:
                key = fp.strip()
                if key not in seen:
                    seen.add(key)
                    paths.append(key)
        # code.search hits
        if name == "code.search" and text:
            try:
                data = json.loads(text)
                hits = data.get("hits") if isinstance(data, dict) else []
                for h in hits[:20] if isinstance(hits, list) else []:
                    if isinstance(h, dict):
                        fp = h.get("file_path")
                        if fp and isinstance(fp, str) and len(fp.strip()) >= 2:
                            key = fp.strip()
                            if key not in seen:
                                seen.add(key)
                                paths.append(key)
            except (json.JSONDecodeError, TypeError):
                pass
            # 正则兜底
            for m in re.finditer(r'"file_path"\s*:\s*"([^"]+)"', text):
                fp = m.group(1).strip()
                if len(fp) >= 2 and fp not in seen:
                    seen.add(fp)
                    paths.append(fp)

        if len(paths) >= MAX_RULE_PATH_CANDIDATES:
            break

    return paths[:MAX_RULE_PATH_CANDIDATES]


def build_rule_context_hint(paths: list[str], max_show: int = 10) -> str:
    """根据提取的路径生成规则提示，供 Plan 参考。"""
    if not paths:
        return ""
    shown = paths[:max_show]
    return f"已涉及路径: {', '.join(shown)}{'...' if len(paths) > max_show else ''}"
