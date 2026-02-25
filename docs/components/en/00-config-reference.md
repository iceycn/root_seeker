# Config Reference

Full list of `config.yaml` options.

## Top-Level

| Key | Type | Default | Description |
|-----|------|---------|-------------|
| data_dir | str | data | Data directory |
| audit_dir | str | data/audit | Audit log directory |
| api_keys | list | [] | API keys; requests need X-API-Key when non-empty |
| analysis_workers | int | 2 | Analysis worker concurrency |
| llm_concurrency | int | 4 | LLM concurrency |
| git_timeout_seconds | int | 180 | Git operation timeout |
| analysis_timeout_seconds | int | 160 | Single analysis task timeout |
| log_level | str | INFO | Log level |
| evidence_level | str | L3 | Evidence level |
| max_evidence_files | int | 12 | Max evidence files |
| max_evidence_chunks | int | 24 | Max evidence chunks |
| max_context_chars_total | int | 160000 | Total evidence char limit |
| max_context_chars_per_file | int | 24000 | Per-file char limit |

## aliyun_sls

| Key | Description |
|-----|-------------|
| endpoint | SLS API endpoint |
| access_key_id | AccessKey ID |
| access_key_secret | AccessKey Secret |
| project | SLS project name |
| logstore | Logstore name |
| topic | Optional |

## sql_templates

| Key | Description |
|-----|-------------|
| query_key | Template ID, matches ingest param |
| query | SLS query SQL; supports {service_name}, {start_ts}, {end_ts}, {trace_id}, {request_id} |

## repos

| Key | Description |
|-----|-------------|
| service_name | Service name |
| git_url | Git repo URL |
| local_dir | Local path |
| repo_aliases | Alias list |
| language_hints | Language hints |

## zoekt

| Key | Description |
|-----|-------------|
| api_base_url | Zoekt URL, e.g. http://127.0.0.1:6070 |

## qdrant

| Key | Description |
|-----|-------------|
| url | Qdrant URL |
| api_key | Optional, for auth |
| collection | Vector collection name |

## llm

| Key | Description |
|-----|-------------|
| kind | deepseek \| doubao |
| base_url | API URL |
| api_key | API Key |
| model | Model name |
| timeout_seconds | Timeout in seconds |
| temperature | Optional |
| max_tokens | Optional |

## embedding

| Key | Description |
|-----|-------------|
| kind | fastembed \| hash |
| model_name | Model name |
| cache_dir | Optional, cache dir |

## wecom / dingtalk

| Key | Description |
|-----|-------------|
| webhook_url | Webhook URL |

## Optional Features

See `config.example.yaml` comments for: cross_repo_evidence, call_graph_expansion, llm_multi_turn_*, trace_chain_*, periodic_tasks_*.

[中文](../00-config-reference.md)
