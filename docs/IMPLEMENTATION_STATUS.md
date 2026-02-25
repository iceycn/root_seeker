# 实现状态总结

本文档总结当前项目与需求的实现对照，便于快速了解已完成与待优化项。

## 一、核心需求实现状态

| 需求 | 状态 | 说明 |
|------|------|------|
| 根据错误信息路由到指定仓库 | ✅ 已实现 | `ServiceRouter` 支持显式映射 + 启发式推断 |
| 在指定仓库中通过 AI 检索内容 | ✅ 已实现 | Zoekt（词法）+ Qdrant（向量）+ Tree-sitter（切分） |
| **分析代码片段，进一步找出更多的关联内容、上下游方法片段，直到找出所有的关联内容** | ✅ **已实现** | `CallGraphExpander` 支持方法级调用链展开与迭代扩展 |
| 分析错误原因并给出修改建议 | ✅ 已实现 | LLM（DeepSeek/豆包 API）生成报告 |
| 列出关联服务 | ✅ 已实现 | `ServiceGraph` 解析服务依赖，报告中有 `related_services` |
| 支持通过关联项在多个仓库中检索关联代码片段 | ✅ 已实现 | `cross_repo_evidence` 在关联服务仓库内做向量检索 |

## 二、P0 优化项（影响正确性）

| 项 | 状态 | 实现位置 |
|----|------|----------|
| SLS 时间窗与事件时间一致 | ✅ 已完成 | `providers/sls.py` 支持 `from_ts`/`to_ts`；`enricher.py` 根据事件时间计算时间窗 |
| query_key 缺失时的默认行为 | ✅ 已完成 | `domain.py` 默认值 `"default_error_context"`；`enricher.py` 兜底逻辑 |

## 三、P1 优化项（体验与可运维性）

| 项 | 状态 | 实现位置 |
|----|------|----------|
| Zoekt 按 repo 过滤 | ✅ 已完成 | `analyzer.py` 中查询字符串添加 `repo:{repo_name}` 过滤器 |
| 钉钉配置示例 | ✅ 已完成 | `config.example.yaml` 中钉钉配置块已提供 |
| 健康检查与依赖探测 | ✅ 已完成 | `/healthz?check_deps=true` 检查 Zoekt/Qdrant 可达性 |
| 分析超时与 3 分钟 SLA | ✅ 已完成 | `config.analysis_timeout_seconds`（默认 160 秒）；`job_queue.py` 超时处理 |

## 四、P2 优化项（扩展与安全）

| 项 | 状态 | 说明 |
|----|------|------|
| 方法级上下游代码展开 | ✅ **已完成并优化** | `CallGraphExpander` 支持：<br>- Tree-sitter 精确解析（`call_graph_use_tree_sitter`）<br>- 异步 Zoekt 集成（优先使用 Zoekt 搜索方法名）<br>- 性能优化：方法定位缓存（LRU）、文件解析缓存、扫描范围限制（`call_graph_scan_limit_dirs`）、全仓库扫描限制文件数 |
| 向量库/切分/词法检索可替换 | 🔄 已预留 | `protocols.py` 定义 Protocol，待实现工厂与 config kind |
| 证据包外发脱敏 | ⏳ 待实现 | 建议在 `EvidenceBuilder` 或发送 LLM 前增加脱敏过滤器 |
| 白名单控制外发 | ⏳ 待实现 | 建议增加 `allow_llm_export_services` 配置 |
| 多 LLM / 豆包 URL | ⏳ 待实现 | 当前支持单组 LLM，可扩展为列表或按 kind 选择 |
| 语言扩展（Go/TS 等） | ⏳ 待实现 | Tree-sitter 与 chunker 需增加对应 parser |

## 五、P3 优化项（性能与规模）

| 项 | 状态 | 说明 |
|----|------|------|
| 百仓同步并发可配置 | ⏳ 待实现 | 当前硬编码 `Semaphore(8)`，建议配置化 |
| 向量索引增量 | ⏳ 待实现 | 当前全量覆盖，可考虑按文件 hash 增量更新 |
| 审计日志轮转 | ⏳ 待实现 | 当前单文件追加，建议按日/大小轮转 |

## 六、新增功能（本次优化）

| 功能 | 状态 | 说明 |
|------|------|------|
| 方法级调用链展开 | ✅ 已实现 | `CallGraphExpander` 支持从代码片段解析方法调用并迭代扩展 |
| 控制台打印报告 | ✅ 已实现 | `ConsoleNotifier`，`notify_console: true` 时打印到日志 |
| 文件存储报告 | ✅ 已实现 | `FileReportStoreNotifier`，`report_store_path` 非空时写入文件 |
| 多通道通知 | ✅ 已实现 | 支持同时启用企业微信、钉钉、控制台、文件存储 |
| 可替换组件 Protocol | ✅ 已定义 | `protocols.py` 定义 `VectorStoreProtocol`、`ChunkerProtocol`、`LexicalSearchProtocol` |
| RepoConfig.feature 字段 | ✅ 已实现 | 支持特性标签，便于后续按特性过滤 |

## 七、配置项汇总

### 新增配置项（本次优化）

```yaml
# 方法级调用链展开
call_graph_expansion: false
call_graph_max_rounds: 2
call_graph_max_methods_per_round: 5
call_graph_max_total_methods: 15
call_graph_use_tree_sitter: true   # 使用 Tree-sitter 解析（更精确）
call_graph_scan_limit_dirs: ["src/main", "src"]   # 限制扫描目录（大仓库建议）
call_graph_cache_size: 100   # 方法定位缓存大小

# 报告输出扩展
notify_console: false
report_store_path: null

# 分析超时
analysis_timeout_seconds: 160

# 仓库配置扩展
repos:
  - service_name: "..."
    feature: []  # 可选特性标签
```

## 八、测试与验证

- ✅ 所有现有测试通过（4 个测试用例）
- ✅ 无 linter 错误
- ✅ 配置项向后兼容（新增项均有默认值）

## 九、后续建议

1. **P2 安全项**：优先实现证据包脱敏与白名单控制，保障生产环境安全。
2. **P3 性能项**：在仓库数量达到上百个时，考虑实现向量索引增量与并发配置优化。
3. **语言扩展**：根据实际需求逐步增加 Go/TypeScript 等语言支持。
