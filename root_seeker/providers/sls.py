from __future__ import annotations

import asyncio
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Protocol

from root_seeker.domain import LogBundle, LogRecord


class CloudLogProvider(Protocol):
    async def query(
        self, *, query_key: str, query: str, from_ts: int | None = None, to_ts: int | None = None
    ) -> LogBundle: ...


@dataclass(frozen=True)
class AliyunSlsQueryConfig:
    endpoint: str
    access_key_id: str
    access_key_secret: str
    project: str
    logstore: str
    topic: str | None = None


class AliyunSlsProvider:
    def __init__(self, cfg: AliyunSlsQueryConfig):
        self._cfg = cfg

        try:
            from aliyun.log import LogClient  # type: ignore
        except Exception as e:  # pragma: no cover
            raise RuntimeError(
                "Aliyun SLS SDK is not installed. Install dependency: aliyun-log-python-sdk"
            ) from e

        self._client = LogClient(
            endpoint=cfg.endpoint,
            accessKeyId=cfg.access_key_id,
            accessKey=cfg.access_key_secret,
        )

    async def query(
        self,
        *,
        query_key: str,
        query: str,
        from_ts: int | None = None,
        to_ts: int | None = None,
    ) -> LogBundle:
        """
        查询 SLS 日志。

        Args:
            query_key: SQL 模板 key
            query: SQL 查询语句
            from_ts: 起始时间戳（秒），若不传则使用 now-3600
            to_ts: 结束时间戳（秒），若不传则使用 now+60
        """
        now_ts = int(datetime.now(tz=timezone.utc).timestamp())
        from_time = from_ts if from_ts is not None else now_ts - 3600
        to_time = to_ts if to_ts is not None else now_ts + 60

        def _do_query():
            return self._client.get_log(
                project=self._cfg.project,
                logstore=self._cfg.logstore,
                from_time=from_time,
                to_time=to_time,
                topic=self._cfg.topic,
                query=query,
                size=200,
                offset=0,
                reverse=True,
            )

        resp = await asyncio.to_thread(_do_query)

        records: list[LogRecord] = []
        for item in resp.get_logs():
            content = item.get_contents()
            msg = content.get("message") or content.get("msg") or str(content)
            records.append(LogRecord(message=msg, fields=content))

        return LogBundle(query_key=query_key, records=records, raw=resp.get_body())
