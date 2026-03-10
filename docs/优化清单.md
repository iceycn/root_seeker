# 优化建议清单

在保持现有架构的前提下，建议按优先级推进以下优化。

## P0（影响正确性 / 与需求不符）

| 项 | 说明 | 位置 |
|----|------|------|
| ~~SLS 时间窗与事件时间一致~~ | ~~当前 `providers/sls.py` 的 `get_log` 使用固定 `now-3600`～`now+60`，未使用事件的 `timestamp`。应支持传入 `from_ts`/`to_ts`（或由 enricher 传入），使「补全日志」的时间窗与错误发生时间一致。~~ | ✅ **已实现**：`providers/sls.py` 的 `query` 方法支持 `from_ts`/`to_ts` 参数；`enricher.py` 根据事件的 `timestamp` 与 `time_window_seconds` 计算并传入时间窗。 |
| ~~query_key 缺失时的行为~~ | ~~若 Webhook 未传 `query_key` 或传了未在 `sql_templates` 中配置的 key，enricher 会抛 `KeyError`。建议：默认使用 `default_error_context` 或返回空 LogBundle 并带 note，避免整条分析失败。~~ | ✅ **已实现**：`domain.py` 中 `IngestEvent.query_key` 默认值为 `"default_error_context"`；`enricher.py` 中当 query_key 不存在时先尝试默认值，若仍不存在则返回空 LogBundle，避免整条分析失败。 |

## P1（体验与可运维性）

| 项 | 说明 | 位置 |
|----|------|------|
| ~~Zoekt 与「仓库路径」的对应~~ | ~~当前 Zoekt 客户端未按 `repo_local_dir` 或 service 过滤，若多仓库都建在同一 Zoekt 实例，需要按 repo 名/路径过滤。建议：在 `ZoektClient.search` 中支持按 repo 列表过滤，或文档明确「一个 Zoekt 对应一个 repo/索引名」的部署方式。~~ | ✅ **已实现**：`analyzer.py` 中 `_build_zoekt_query` 支持 `repo_name` 参数，在查询字符串中添加 `repo:{repo_name}` 过滤器（Zoekt 查询语法支持）；同时保留后过滤 `_filter_zoekt_hits_for_repo` 作为兜底。 |
| ~~钉钉配置示例~~ | ~~`config.example.yaml` 仅有企业微信，建议增加钉钉示例块，与 README/部署文档一致。~~ | ✅ **已实现**：`config.example.yaml` 中钉钉配置块已取消注释，提供完整示例。 |
| ~~健康检查与依赖~~ | ~~`GET /healthz` 仅返回 200，可增加可选「依赖探测」：Zoekt/Qdrant 可达性，便于运维做就绪探针。~~ | ✅ **已实现**：`app.py` 中 `/healthz` 接口支持 `check_deps` 查询参数，为 true 时检查 Zoekt/Qdrant 可达性并返回状态（`/healthz?check_deps=true`）。 |
| ~~分析超时与 3 分钟 SLA~~ | ~~单次分析若 LLM 或 SLS 较慢，可能超过 3 分钟。建议：为 analyzer.analyze 或 job 配置超时，超时后标记 failed 并写入 status_store，避免无限挂起。~~ | ✅ **已实现**：`config.py` 中添加 `analysis_timeout_seconds`（默认 160 秒）；`job_queue.py` 中使用 `asyncio.wait_for` 包装 `analyzer.analyze`，超时后标记 `failed` 并写入 `status_store`。 |

## P2（扩展与安全）

| 项 | 说明 | 位置 |
|----|------|------|
| **方法级上下游代码展开** | ✅ **已实现并优化**：`services/call_graph_expander.py` 中的 `CallGraphExpander` 类，支持：<br>1. **Tree-sitter 精确解析**：优先使用 Tree-sitter 解析方法调用关系（`call_graph_use_tree_sitter: true`），回退到正则<br>2. **异步 Zoekt 集成**：支持异步调用 Zoekt 搜索方法名，优先使用 Zoekt 定位方法<br>3. **性能优化**：<br>   - 方法定位缓存（LRU，`call_graph_cache_size`）<br>   - 文件解析缓存（避免重复解析同一文件）<br>   - 扫描范围限制（`call_graph_scan_limit_dirs`，优先扫描 `src/main`、`src` 等常见目录，大仓库建议限制）<br>   - 全仓库扫描时限制文件数（最多 200 个文件）<br>配置项：`call_graph_expansion`、`call_graph_max_rounds`、`call_graph_max_methods_per_round`、`call_graph_max_total_methods`、`call_graph_use_tree_sitter`、`call_graph_scan_limit_dirs`、`call_graph_cache_size`。 | ✅ **已完成** |
| 向量库/切分/词法检索可替换 | 已定义 `VectorStoreProtocol`、`ChunkerProtocol`、`LexicalSearchProtocol`（`protocols.py`），当前实现符合。后续可增加 config 中 `vector_store.kind`、`chunker.kind`、`lexical_search.kind` 与工厂，按配置选择实现（如 Milvus、OpenGrok）。 | `root_seeker/protocols.py`、config、app 工厂 |
| 证据包外发脱敏 | 方案要求对 AK/SK、Token、Cookie 等脱敏。当前证据包直接拼进 LLM 上下文，建议在 EvidenceBuilder 或发送 LLM 前增加一层脱敏过滤器（可配置正则或关键字）。 | `services/evidence.py` 或新建 `security/sanitize.py` |
| 白名单控制外发 | 方案要求「仅允许指定 repo/service 外发」。建议：在配置中增加 `allow_llm_export_services: list[str]`，在 analyzer 中若 service_name 不在白名单则不走 LLM，仅做检索与本地报告。 | `config.py`、`services/analyzer.py` |
| 多 LLM / 豆包 URL | 当前 LLM 配置为单组 base_url + model。若需同时支持 DeepSeek 与豆包，可扩展为 `llm.providers` 列表或按 `kind` 选择不同 base_url。 | `config.py`、`app.py` |
| 语言扩展 | Tree-sitter 与 chunker 已支持 Python/Java，若需 Go/TS 等，在 `indexing/chunker.py` 中增加语言检测与对应 parser 即可；需同步在 `service_graph` 的依赖解析里增加新语言模式。 | `indexing/chunker.py`、`services/service_graph.py` |

## P3（性能与规模）

| 项 | 说明 | 位置 |
|----|------|------|
| 百仓同步并发与限流 | `POST /repos/sync` 使用 asyncio.gather + Semaphore(8)，可配置化（如 `repos_sync_concurrency`），避免同一机器上对 Git 服务器压力过大。 | `config.py`、`app.py` |
| 向量索引增量 | 当前 `index_repo` 为全量覆盖（先 chunk 再 upsert）。若 Qdrant 按 `repo_local_dir`+`file_path` 等做 payload 过滤，可考虑「按文件 hash 只更新变更文件」以缩短大仓索引时间。 | `services/vector_indexer.py`、`providers/qdrant.py` |
| 审计日志轮转 | 审计日志单文件追加，长期会变大。建议按日或按大小轮转，或对接公司日志平台。 | `storage/audit_log.py` |

---

以上清单可与「项目结构说明」「部署文档」一起作为迭代依据；P0 建议优先在下一版本完成。
