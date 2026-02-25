# 配置项完整参考

本文档列出 `config.yaml` 中所有配置项，便于快速查阅。

## 顶层配置

| 配置项 | 类型 | 默认值 | 说明 |
|--------|------|--------|------|
| data_dir | str | data | 数据目录 |
| audit_dir | str | data/audit | 审计日志目录 |
| api_keys | list | [] | API Key 列表，非空时请求需带 X-API-Key |
| analysis_workers | int | 2 | 分析任务并发 worker 数 |
| llm_concurrency | int | 4 | LLM 并发数 |
| git_timeout_seconds | int | 180 | Git 操作超时 |
| analysis_timeout_seconds | int | 160 | 单次分析任务超时 |
| log_level | str | INFO | 日志级别 |
| evidence_level | str | L3 | 证据级别 |
| max_evidence_files | int | 12 | 最大证据文件数 |
| max_evidence_chunks | int | 24 | 最大证据块数 |
| max_context_chars_total | int | 160000 | 证据总字符上限 |
| max_context_chars_per_file | int | 24000 | 单文件字符上限 |

## aliyun_sls

| 配置项 | 说明 |
|--------|------|
| endpoint | SLS API 地址 |
| access_key_id | AccessKey ID |
| access_key_secret | AccessKey Secret |
| project | SLS 项目名 |
| logstore | Logstore 名 |
| topic | 可选 |

## sql_templates

| 配置项 | 说明 |
|--------|------|
| query_key | 模板标识，与 ingest 入参对应 |
| query | SLS 查询 SQL，支持 {service_name}、{start_ts}、{end_ts}、{trace_id}、{request_id} |

## repos

| 配置项 | 说明 |
|--------|------|
| service_name | 服务名 |
| git_url | Git 仓库地址 |
| local_dir | 本地路径 |
| repo_aliases | 别名列表 |
| language_hints | 语言提示 |

## zoekt

| 配置项 | 说明 |
|--------|------|
| api_base_url | Zoekt 服务地址，如 http://127.0.0.1:6070 |

## qdrant

| 配置项 | 说明 |
|--------|------|
| url | Qdrant 地址 |
| api_key | 可选，鉴权用 |
| collection | 向量集合名 |

## llm

| 配置项 | 说明 |
|--------|------|
| kind | deepseek \| doubao |
| base_url | API 地址 |
| api_key | API Key |
| model | 模型名 |
| timeout_seconds | 超时秒数 |
| temperature | 可选 |
| max_tokens | 可选 |

## embedding

| 配置项 | 说明 |
|--------|------|
| kind | fastembed \| hash |
| model_name | 模型名 |
| cache_dir | 可选，缓存目录 |

## wecom / dingtalk

| 配置项 | 说明 |
|--------|------|
| webhook_url | Webhook 地址 |
| security_mode | 安全模式：sign（加签）\| keyword（关键词）\| ip（IP 白名单） |
| secret | security_mode=sign 时必填，加签密钥 |

## 可选功能（跨仓库、调用链、多轮对话等）

见 `config.example.yaml` 中的注释，包括：

- cross_repo_evidence、cross_repo_max_services、cross_repo_max_chunks_per_service
- call_graph_expansion、call_graph_max_rounds 等
- llm_multi_turn_enabled、llm_multi_turn_mode 等
- trace_chain_enabled、trace_chain_time_window_seconds 等
- periodic_tasks_enabled、auto_sync_enabled 等

[English](en/00-config-reference.md)
