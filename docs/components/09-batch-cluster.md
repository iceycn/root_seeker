# 批量日志聚类接口

`POST /ingest/batch-cluster` 用于将一批可能来自多个服务的错误日志进行聚类，将相似问题归为一组，每组抽样一条进行分析。**尽量少用 AI**：聚类主要依赖指纹哈希与本地 embedding，不调用 LLM。

## 一、使用场景

- 从 SLS、Sentry、Kafka 等批量拉取错误日志
- 日志可能来自多个服务
- 希望减少重复分析：相似错误只分析一次

## 二、请求格式

`logs` 数组中每项与 `POST /ingest`、`POST /ingest/aliyun-sls` 单条格式一致：

```json
{
  "logs": [
    {
      "service_name": "order-service",
      "error_log": "NullPointerException: ...",
      "query_key": "default_error_context",
      "timestamp": null,
      "tags": {}
    },
    {"content": "...", "__time__": 1234567890, "__tag__": {...}}
  ],
  "submit_for_analysis": true
}
```

- `logs`：必填，JSON 数组。每项与 `/ingest` 一致：
  - **标准格式**（同 `/ingest`）：`service_name`、`error_log`、`query_key`、`timestamp`、`tags`
  - **SLS 格式**（同 `/ingest/aliyun-sls`）：`content`、`__time__`、`__tag__`
- `submit_for_analysis`：可选，默认 `true`。为 `true` 时，每组代表样本会自动入队分析。

也可直接传数组：`[{...}, {...}]`，此时默认 `submit_for_analysis=true`。

## 三、聚类算法

**若配置了 Qdrant + Embedding**（`config.yaml` 中 `qdrant` 与 `embedding` 均非空），则使用 embedding 方案：

- 对 ≤2000 条日志做向量相似度聚类（余弦相似度 ≥0.88 合并）
- 使用本地 FastEmbed 模型，不调用 LLM
- 响应中 `clustering_method` 为 `"embedding"`

**若未配置** Qdrant 或 Embedding，则退化为指纹哈希方案：

- 从错误文本提取异常类型、首行消息、堆栈签名（去掉行号），做 SHA256 哈希分组
- 零 AI、零外部依赖
- 响应中 `clustering_method` 为 `"fingerprint"`

## 四、响应示例

```json
{
  "status": "ok",
  "total_logs": 150,
  "total_clusters": 12,
  "clustering_method": "embedding",
  "clusters": [
    {"size": 25, "representative_index": 0, "service_name": "order-service"},
    {"size": 8, "representative_index": 32, "service_name": "payment-service"}
  ],
  "analysis_ids": ["abc123...", "def456..."]
}
```

- `analysis_ids`：当 `submit_for_analysis=true` 时，每组代表样本的 `analysis_id`，可用于 `GET /analysis/{id}` 查询。

## 五、限制

- 单次请求最多 5000 条日志
- embedding 聚类仅在日志数 ≤2000 时启用，超过则仅用指纹分组

[← 配置参考](00-config-reference.md) | [返回文档索引](../DOCUMENTATION_INDEX.md)
