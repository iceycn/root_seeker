"""
通过 trace_id 查询日志链的接口定义和实现。

支持：
- 空实现（未配置时返回空列表）
- 阿里云 SLS 实现（通过 trace_id/request_id 查询日志链）
"""
from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Protocol

from root_seeker.domain import LogBundle, LogRecord

logger = logging.getLogger(__name__)


class TraceChainProvider(Protocol):
    """
    通过 trace_id 查询日志链的接口。
    
    接口方法：
    - query_by_trace_id: 根据 trace_id 和时间范围查询日志链
    """
    
    async def query_by_trace_id(
        self,
        *,
        trace_id: str | None,
        request_id: str | None,
        from_time: datetime,
        to_time: datetime,
    ) -> LogBundle:
        """
        根据 trace_id/request_id 和时间范围查询日志链。
        
        Args:
            trace_id: 追踪ID（可选）
            request_id: 请求ID（可选，至少需要提供 trace_id 或 request_id 之一）
            from_time: 查询起始时间
            to_time: 查询结束时间
            
        Returns:
            LogBundle: 包含查询到的日志记录
            
        Note:
            - 时间范围不应超过 MAX_TIME_WINDOW_SECONDS（5分钟）
            - 如果 trace_id 和 request_id 都为空，应返回空的 LogBundle
        """
        ...


@dataclass(frozen=True)
class EmptyTraceChainProvider:
    """
    空实现：当未配置 trace chain provider 时使用，直接返回空列表。
    """
    
    async def query_by_trace_id(
        self,
        *,
        trace_id: str | None,
        request_id: str | None,
        from_time: datetime,
        to_time: datetime,
    ) -> LogBundle:
        """空实现：返回空的 LogBundle"""
        logger.debug("[EmptyTraceChainProvider] 未配置 trace chain provider，返回空列表")
        return LogBundle(query_key="trace_chain", records=[], raw=None)


@dataclass(frozen=True)
class AliyunTraceChainProviderConfig:
    """阿里云 SLS trace chain provider 配置"""
    endpoint: str
    access_key_id: str
    access_key_secret: str
    project: str
    logstore: str
    topic: str | None = None
    max_time_window_seconds: int = 300  # 最大时间窗口（秒），默认5分钟
    timeout_seconds: int = 30  # 单次查询超时（秒），与 httpx/Qdrant 超时策略一致


class AliyunTraceChainProvider:
    """
    阿里云 SLS 实现：通过 trace_id/request_id 查询日志链。
    
    使用全文查询（因为不知道 trace_id 在日志中的具体字段名），
    查询语法：`(trace_id_value or request_id_value) | select * from log where ...`
    """
    
    def __init__(self, cfg: AliyunTraceChainProviderConfig):
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
        logger.info(f"[AliyunTraceChainProvider] 初始化完成，project={cfg.project}, logstore={cfg.logstore}")
    
    async def query_by_trace_id(
        self,
        *,
        trace_id: str | None,
        request_id: str | None,
        from_time: datetime,
        to_time: datetime,
    ) -> LogBundle:
        """
        通过 trace_id/request_id 查询日志链。
        
        时间范围限制：不超过 MAX_TIME_WINDOW_SECONDS（5分钟）
        """
        import asyncio
        
        # 如果 trace_id 和 request_id 都为空，返回空列表
        if not trace_id and not request_id:
            logger.debug("[AliyunTraceChainProvider] trace_id 和 request_id 都为空，返回空列表")
            return LogBundle(query_key="trace_chain", records=[], raw=None)
        
        # 验证并限制时间范围（不超过配置的最大值）
        max_window = self._cfg.max_time_window_seconds
        time_diff = (to_time - from_time).total_seconds()
        if time_diff > max_window:
            logger.warning(
                f"[AliyunTraceChainProvider] 时间范围 {time_diff} 秒超过最大限制 {max_window} 秒，"
                f"自动调整为 {max_window} 秒"
            )
            # 以 from_time 为基准，向前扩展配置的最大时间窗口
            to_time = from_time + timedelta(seconds=max_window)
        
        # 构建查询：SLS 不支持「短语查询」(#"value" 或 "value") 与 | select 同时使用。
        # 注：trace_id/request_id 若未在 logstore 配置为 key-value 索引，不能用 field:value 语法，否则报错。
        # 方案：仅用纯值全文搜索，枚举四种格式 val、[val、val]、[val]。
        start_ts = int(from_time.timestamp())
        end_ts = int(to_time.timestamp())
        
        def _build_value_conditions(val: str) -> list[str]:
            # 四种格式：val、[val、val]、[val]
            return [val, f"[{val}", f"{val}]", f"[{val}]"]
        
        all_conditions: list[str] = []
        if trace_id:
            all_conditions.extend(_build_value_conditions(trace_id))
        if request_id and request_id != trace_id:
            all_conditions.extend(_build_value_conditions(request_id))
        condition_str = " or ".join(dict.fromkeys(all_conditions))
        if not condition_str:
            return LogBundle(query_key="trace_chain", records=[], raw=None)
        
        query = (
            f"({condition_str}) | "
            f"select * from log "
            f"where __time__ >= {start_ts} and __time__ <= {end_ts} "
            f"order by __time__ asc limit 500"
        )
        
        logger.info(
            f"[AliyunTraceChainProvider] 查询日志链，trace_id={trace_id}, request_id={request_id}, "
            f"时间范围={from_time.isoformat()} ~ {to_time.isoformat()}"
        )
        logger.debug(f"[AliyunTraceChainProvider] SQL 查询：{query}")
        
        def _do_query():
            return self._client.get_log(
                project=self._cfg.project,
                logstore=self._cfg.logstore,
                from_time=start_ts,
                to_time=end_ts,
                topic=self._cfg.topic,
                query=query,
                size=500,
                offset=0,
                reverse=False,  # 按时间正序排列
            )
        
        try:
            resp = await asyncio.wait_for(
                asyncio.to_thread(_do_query),
                timeout=float(self._cfg.timeout_seconds),
            )
            
            records: list[LogRecord] = []
            for item in resp.get_logs():
                content = item.get_contents()
                msg = content.get("message") or content.get("msg") or str(content)
                records.append(LogRecord(message=msg, fields=content))
            
            logger.info(f"[AliyunTraceChainProvider] 查询完成，返回 {len(records)} 条记录")
            return LogBundle(query_key="trace_chain", records=records, raw=resp.get_body())
        except Exception as e:
            logger.error(f"[AliyunTraceChainProvider] 查询失败：{e}", exc_info=True)
            # 查询失败时返回空列表，不抛出异常
            return LogBundle(query_key="trace_chain", records=[], raw=None)
