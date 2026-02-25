# 日志链自动读取功能设计与实现方案

## 一、当前实现情况

### 1.1 已实现的功能

✅ **被动日志补全**：
- Webhook 接收错误事件
- 根据 `query_key` 选择 SQL 模板
- 根据事件时间窗口（前后各 300 秒）查询 SLS 日志
- 使用参数：`service_name`、`error_log`、`start_ts`、`end_ts`

✅ **自动读取日志链（已实现）**：
- ✅ **使用 LLM 智能提取 trace_id/request_id**：从错误日志中智能识别 trace_id 和 request_id
- ✅ **调用链日志查询**：根据提取的 trace_id/request_id 查询调用链日志
- ✅ **SQL 模板支持**：支持 `{trace_id}` 和 `{request_id}` 参数
- ✅ **跨服务查询**：可以查询所有包含相同 trace_id/request_id 的日志（不限于当前服务）
- ✅ **日志合并**：将调用链日志与基础日志合并，按时间排序

### 1.2 实现特点

**智能提取策略（三级优先级）**：
1. **优先级1**：从 `event.tags` 中提取（如果 webhook 显式传递）
2. **优先级2**：使用 LLM 从错误日志中智能提取（推荐，最准确）
3. **优先级3**：正则匹配（回退方案，如果 LLM 不可用或提取失败）

## 二、需求分析

### 2.1 日志链的概念

**调用链日志**：一次请求经过多个服务，每个服务都会产生日志，这些日志通过 `trace_id` 或 `request_id` 关联。

**示例**：
```
请求流程：
用户请求 → Service A → Service B → Service C

日志链：
Service A: [trace_id: abc123] 开始处理请求
Service B: [trace_id: abc123] 调用 Service B
Service C: [trace_id: abc123] 处理业务逻辑
Service C: [trace_id: abc123] ERROR: 发生错误
```

### 2.2 需要实现的功能

1. **提取 trace_id/request_id**：
   - 从错误日志中提取 `trace_id` 或 `request_id`
   - 支持多种格式（日志格式、JSON 格式等）

2. **查询调用链日志**：
   - 根据 `trace_id`/`request_id` 查询所有相关服务的日志
   - 支持跨服务查询（不限于当前服务）

3. **SQL 模板扩展**：
   - 支持 `{trace_id}` 和 `{request_id}` 参数
   - 支持跨服务查询模板

4. **日志链合并**：
   - 将调用链日志合并到 `LogBundle` 中
   - 按时间排序，便于分析

## 三、实现方案（已实现）

### 3.1 核心设计：使用 LLM 智能提取 trace_id

**为什么使用 LLM**：
- 错误日志格式多样，正则难以覆盖所有情况
- LLM 可以理解上下文，更准确地识别 trace_id
- 支持各种格式：UUID、长字符串、JSON 格式、日志格式等

**提取策略（三级优先级）**：
1. **优先级1**：从 `event.tags` 中提取（如果 webhook 显式传递）
2. **优先级2**：使用 LLM 从错误日志中智能提取（推荐）
3. **优先级3**：正则匹配（回退方案）

### 3.2 LLM 提取 trace_id 的 Prompt 设计

**System Prompt**：
```
你是一个日志分析专家。你的任务是从错误日志中识别 trace_id 和 request_id。
这些标识符通常用于关联分布式系统中的请求调用链。
输出必须是 JSON 格式，不要包含多余文本。
```

**User Prompt**：
```
请从以下错误日志中识别 trace_id 和 request_id。

错误日志：
[错误日志内容，最多 3000 字符]

请分析日志内容，找出最可能是 trace_id 和 request_id 的值。
常见的格式包括：
- UUID 格式：36dfc57c26a84cdcbdc608d8e1d31ee3
- 长字符串：0a690987177010502886340281
- 在日志中以 [trace_id: xxx] 或 trace_id=xxx 等形式出现
- 在 JSON 格式的日志中以 trace_id 或 request_id 字段出现

如果找不到，返回 null。

请输出 JSON 格式：
{"trace_id": "xxx 或 null", "request_id": "xxx 或 null"}
```

### 3.3 调用链查询流程

**如果提取到 trace_id/request_id**：
1. 使用 `trace_chain` SQL 模板查询调用链
2. SQL 模板支持 `{trace_id}` 或 `{request_id}` 参数
3. 查询时间窗口更宽（默认前后各 600 秒，可配置）

**SQL 模板**：
```sql
(trace_id:{trace_id} or request_id:{request_id}) | 
select * from log 
where __time__ >= {start_ts} and __time__ <= {end_ts} 
order by __time__ asc 
limit 500
```

**日志合并**：
- 将调用链日志与基础日志合并
- 按时间排序
- 保留来源信息（base + chain）

### 3.2 实现细节

#### 3.2.1 扩展 IngestEvent 和 NormalizedErrorEvent

```python
class IngestEvent(BaseModel):
    service_name: str
    error_log: str
    query_key: str = Field(default="default_error_context")
    timestamp: datetime | None = None
    tags: dict[str, Any] = Field(default_factory=dict)
    # 新增：显式传递 trace_id/request_id（可选）
    trace_id: str | None = None
    request_id: str | None = None
```

#### 3.2.2 扩展 LogEnricher

```python
class LogEnricher:
    async def enrich(self, event: NormalizedErrorEvent) -> LogBundle:
        # 1. 提取 trace_id/request_id
        trace_id = self._extract_trace_id(event)
        request_id = self._extract_request_id(event)
        
        # 2. 基础日志补全（原有逻辑）
        base_bundle = await self._enrich_base(event)
        
        # 3. 如果有 trace_id/request_id，查询调用链
        if trace_id or request_id:
            chain_bundle = await self._enrich_chain(
                event=event,
                trace_id=trace_id,
                request_id=request_id,
            )
            # 合并日志链
            return self._merge_bundles(base_bundle, chain_bundle)
        
        return base_bundle
    
    def _extract_trace_id(self, event: NormalizedErrorEvent) -> str | None:
        """从事件中提取 trace_id"""
        # 1. 从 tags 中提取
        if event.tags:
            trace_id = event.tags.get("trace_id") or event.tags.get("traceId")
            if trace_id:
                return str(trace_id)
        
        # 2. 从错误日志中提取
        import re
        patterns = [
            r"trace_id[:=]\s*([a-zA-Z0-9_-]+)",
            r"traceId[:=]\s*([a-zA-Z0-9_-]+)",
            r"\[([a-zA-Z0-9_-]{32,})\]",  # 常见的 trace_id 格式
        ]
        for pattern in patterns:
            match = re.search(pattern, event.error_log)
            if match:
                return match.group(1)
        
        return None
    
    def _extract_request_id(self, event: NormalizedErrorEvent) -> str | None:
        """从事件中提取 request_id"""
        # 类似 trace_id 的提取逻辑
        ...
    
    async def _enrich_chain(
        self,
        event: NormalizedErrorEvent,
        trace_id: str | None,
        request_id: str | None,
    ) -> LogBundle:
        """查询调用链日志"""
        # 使用 trace_chain 模板
        query_key = "trace_chain"
        try:
            template = self._registry.get(query_key)
        except KeyError:
            # 如果没有配置 trace_chain 模板，返回空
            return LogBundle(query_key=query_key, records=[], raw=None)
        
        # 扩展时间窗口（调用链可能跨更长时间）
        start = event.timestamp - timedelta(seconds=self._cfg.time_window_seconds * 2)
        end = event.timestamp + timedelta(seconds=self._cfg.time_window_seconds * 2)
        
        params = {
            "trace_id": trace_id or "",
            "request_id": request_id or "",
            "start_ts": int(start.timestamp()),
            "end_ts": int(end.timestamp()),
        }
        query = template.render(params)
        return await self._provider.query(
            query_key=query_key,
            query=query,
            from_ts=int(start.timestamp()),
            to_ts=int(end.timestamp()),
        )
    
    def _merge_bundles(self, base: LogBundle, chain: LogBundle) -> LogBundle:
        """合并两个 LogBundle"""
        all_records = list(base.records) + list(chain.records)
        # 按时间排序
        all_records.sort(key=lambda r: r.timestamp or datetime.min.replace(tzinfo=timezone.utc))
        return LogBundle(
            query_key=f"{base.query_key}+{chain.query_key}",
            records=all_records,
            raw={"base": base.raw, "chain": chain.raw},
        )
```

#### 3.2.3 配置 SQL 模板

在 `config.yaml` 中添加：

```yaml
sql_templates:
  - query_key: "default_error_context"
    query: "level:ERROR and service:{service_name} | select * from log where __time__ >= {start_ts} and __time__ <= {end_ts} limit 200"
  
  # 新增：调用链日志查询模板
  - query_key: "trace_chain"
    query: "(trace_id:{trace_id} or request_id:{request_id}) | select * from log where __time__ >= {start_ts} and __time__ <= {end_ts} order by __time__ asc limit 500"
```

## 四、实现总结

### 4.1 已实现的功能

✅ **LLM 智能提取 trace_id/request_id**：
- `_extract_trace_ids_with_llm` 方法：使用 LLM 从错误日志中智能识别
- `_extract_trace_id_regex` 方法：正则匹配（回退方案）
- `_extract_request_id_regex` 方法：正则匹配（回退方案）

✅ **调用链日志查询**：
- `_enrich_chain` 方法：根据 trace_id/request_id 查询调用链日志
- 支持 `trace_chain` SQL 模板
- 可配置的时间窗口（默认 600 秒）

✅ **日志合并**：
- `_merge_bundles` 方法：合并基础日志和调用链日志
- 按时间排序
- 保留来源信息

✅ **配置支持**：
- `trace_chain_enabled`：是否启用调用链查询（默认 true）
- `trace_chain_time_window_seconds`：调用链查询时间窗口（默认 600 秒）
- `trace_chain` SQL 模板：支持 `{trace_id}` 和 `{request_id}` 参数

### 4.2 代码位置

- **实现文件**：`root_seeker/services/enricher.py`
- **配置项**：`root_seeker/config.py`（`trace_chain_enabled`、`trace_chain_time_window_seconds`）
- **SQL 模板**：`config.yaml`（`trace_chain` 模板）

## 五、配置示例

### 5.1 config.yaml

```yaml
sql_templates:
  - query_key: "default_error_context"
    query: "level:ERROR and service:{service_name} | select * from log where __time__ >= {start_ts} and __time__ <= {end_ts} limit 200"
  
  # 调用链日志查询（根据 trace_id/request_id）
  - query_key: "trace_chain"
    query: "(trace_id:{trace_id} or request_id:{request_id}) | select * from log where __time__ >= {start_ts} and __time__ <= {end_ts} order by __time__ asc limit 500"
```

### 5.2 Webhook 调用示例

```json
{
  "service_name": "cmdb-api",
  "error_log": "...",
  "query_key": "default_error_context",
  "timestamp": "2026-02-03T15:50:28Z",
  "tags": {
    "trace_id": "36dfc57c26a84cdcbdc608d8e1d31ee3",
    "request_id": "0a690987177010502886340281"
  }
}
```

或者显式传递：

```json
{
  "service_name": "cmdb-api",
  "error_log": "...",
  "trace_id": "36dfc57c26a84cdcbdc608d8e1d31ee3",
  "request_id": "0a690987177010502886340281"
}
```

## 六、预期效果

### 6.1 功能提升

- **更完整的上下文**：不仅包含当前服务的日志，还包含调用链上所有服务的日志
- **更好的问题定位**：可以看到请求在哪个服务、哪个环节出现问题
- **自动关联**：无需手动配置，自动从错误日志中提取 trace_id

### 6.2 使用场景

1. **分布式系统错误分析**：
   - 一次请求经过多个服务
   - 通过 trace_id 自动关联所有相关日志

2. **调用链分析**：
   - 看到完整的调用路径
   - 分析性能瓶颈和错误传播

## 七、后续优化方向

1. **智能提取**：支持更多 trace_id/request_id 格式
2. **跨服务查询**：如果 trace_id 格式包含服务信息，可以智能查询多个服务
3. **日志去重**：调用链日志可能有重复，需要去重
4. **可视化**：将调用链日志可视化展示

## 八、总结

✅ **功能已实现**：

1. ✅ **LLM 智能提取 trace_id/request_id**：使用大模型从错误日志中智能识别
2. ✅ **SQL 模板支持**：支持 `{trace_id}` 和 `{request_id}` 参数
3. ✅ **调用链日志查询**：根据 trace_id/request_id 查询调用链日志
4. ✅ **日志合并**：将调用链日志与基础日志合并，按时间排序
5. ✅ **配置支持**：可配置启用/禁用、时间窗口等

**使用方式**：
- 默认已启用（`trace_chain_enabled: true`）
- 自动从错误日志中提取 trace_id/request_id
- 如果提取成功，自动查询调用链日志并合并

**优势**：
- 使用 LLM 智能提取，准确率高
- 支持多种格式的 trace_id/request_id
- 自动合并调用链日志，提供更完整的上下文
