from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any

import httpx

from root_seeker.domain import ZoektHit

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class ZoektClientConfig:
    api_base_url: str
    timeout_seconds: float = 10.0


class ZoektClient:
    def __init__(self, cfg: ZoektClientConfig, client: httpx.AsyncClient | None = None):
        self._cfg = cfg
        self._client = client or httpx.AsyncClient(timeout=cfg.timeout_seconds)

    async def search(
        self,
        *,
        query: str,
        repo_ids: list[int] | None = None,
        num_context_lines: int = 5,
        max_matches: int = 50,
    ) -> list[ZoektHit]:
        logger.debug(f"[ZoektClient] 搜索查询：{query}, repo_ids={repo_ids}, max_matches={max_matches}")
        url = f"{self._cfg.api_base_url.rstrip('/')}/api/search"
        payload: dict[str, Any] = {
            "Q": query,
            "Opts": {
                "NumContextLines": num_context_lines,
                "MaxMatchCount": max_matches,
            },
        }
        if repo_ids:
            payload["RepoIDs"] = repo_ids

        try:
            resp = await self._client.post(url, json=payload)
            resp.raise_for_status()
            data = resp.json()

            hits: list[ZoektHit] = []

            # 兼容 google/zoekt (FileMatches) 与 sourcegraph/zoekt (Result.Files)
            file_matches = (
                data.get("FileMatches")
                or data.get("file_matches")
                or data.get("Result", {}).get("Files")
                or []
            )
            logger.debug(f"[ZoektClient] 收到 {len(file_matches)} 个文件匹配")
            if len(file_matches) == 0:
                top_keys = list(data.keys()) if isinstance(data, dict) else []
                result_keys = list(data.get("Result", {}).keys()) if isinstance(data.get("Result"), dict) else []
                logger.warning(
                    f"[ZoektClient] Zoekt 返回 0 命中，响应顶层 keys={top_keys}, "
                    f"Result.keys={result_keys}，请检查：1) 查询词是否在索引中存在 2) repo 名是否匹配"
                )
            for fm in file_matches:
                file_path = fm.get("FileName") or fm.get("file_name") or ""
                repo = fm.get("Repository") or fm.get("repository")
                score = fm.get("Score") or fm.get("score")

                line_number = None
                preview = None
                line_matches = fm.get("LineMatches") or fm.get("line_matches") or []
                if line_matches:
                    lm0 = line_matches[0]
                    line_number = lm0.get("LineNumber") or lm0.get("line_number")
                    preview = lm0.get("Line") or lm0.get("line")

                if file_path:
                    hits.append(
                        ZoektHit(
                            repo=repo,
                            file_path=file_path,
                            line_number=line_number,
                            preview=preview,
                            score=score,
                        )
                    )
            logger.info(f"[ZoektClient] 搜索完成，返回 {len(hits)} 个命中结果")
            return hits
        except Exception as e:
            logger.error(f"[ZoektClient] 搜索失败：{e}", exc_info=True)
            raise

    async def list_indexed_repos(self) -> set[str] | None:
        """
        获取已索引的仓库名列表。使用 sourcegraph/zoekt 的 /api/list 接口（需 -rpc 启动）。
        接口为 POST，请求体需包含 Q（如 r:.* 表示所有仓库），响应在 List.Repos 中。
        """
        try:
            url = f"{self._cfg.api_base_url.rstrip('/')}/api/list"
            payload = {"Q": "r:.*"}  # 匹配所有仓库的查询
            resp = await self._client.post(url, json=payload)
            if resp.status_code != 200:
                logger.warning(f"[ZoektClient] list 返回 {resp.status_code}: {resp.text[:200]}")
                return None
            data = resp.json()
            # 响应格式: {"List": {"Repos": [{"Repository": {"Name": "..."}, ...}, ...], ...}}
            list_obj = data.get("List") or data.get("list") or {}
            repos = list_obj.get("Repos") or list_obj.get("repos") or []
            names = set()
            for r in repos:
                if isinstance(r, dict):
                    repo_obj = r.get("Repository") or r.get("repository") or r
                    n = repo_obj.get("Name") or repo_obj.get("name") or ""
                    if n:
                        names.add(str(n))
                elif isinstance(r, str):
                    names.add(r)
            return names
        except Exception as e:
            logger.warning(f"[ZoektClient] list_indexed_repos 失败: {e}")
            return None

    async def aclose(self) -> None:
        await self._client.aclose()

