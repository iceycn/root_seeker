# RootSeeker v2.0.0 更新说明

## 概述

v2.0.0 是一次重大架构升级，将主流程从「直接调用内部接口」改为 **AI 驱动**，引入 MCP 网关与 AI 网关，支持多轮迭代分析、上下文发现与自主勘探。

---

## 一、核心变更

### 1.1 MCP 网关

- **应用内极简网关**：`McpGateway` 负责工具注册、发现（list_tools）、执行（call_tool）
- **内部工具**：`index.get_status`、`correlation.get_info`、`code.search`、`code.read`、`deps.get_graph`、`analysis.run`、`analysis.run_full`、`analysis.synthesize`、`evidence.context_search`
- **外部 MCP Server**：支持 stdio 与 streamable-http，可接入阿里云可观测 MCP Server 等
- **API 端点**：`GET /mcp/tools`、`POST /mcp/call`

### 1.2 AI 驱动主流程

- **Plan → Act → Synthesize → Check** 多轮迭代
- **勘探优先**：细粒度工具（index/correlation/code.search/evidence.context_search/code.read）优先于全量分析（analysis.run）
- **evidence.context_search**：在已收集证据上下文中检索，主循环与递归证据收集均注入 `evidence_ctx`
- **失败回退**：任意 tool 失败或 Plan 解析失败时自动回退到直连路径

### 1.3 AI 网关

- **动态切换**：支持多套 LLM 配置（DeepSeek、豆包等），运行时切换
- **动态新增**：`add_provider` 支持新增配置
- **ENV 引用**：api_key 支持 `ENV:VAR_NAME` 引用环境变量
- **回退策略**：切换失败自动回退 default_provider

### 1.4 Hook 体系

- **四种 Hook**：AnalysisStart、AnalysisComplete、PreToolUse、PostToolUse
- **目录**：`~/.rootseek/hooks/` + `config.hooks.dirs`
- **可取消**：PreToolUse 可跳过工具，AnalysisStart 可中止分析
- 详见 [Hook体系说明.md](Hook体系说明.md)

---

## 二、分析流程增强

### 2.1 上下文发现

- **预取**：Plan 前预取 `index.get_status`、`correlation.get_info`（若有 trace_id）
- **引用解析**：从 error_log 提取 trace_id、类名、方法名、配置项，注入 Plan 提示
- **RuleContextBuilder**：从 tool_results 提取 file_path、repo_id，注入下一轮 Plan

### 2.2 Check 阶段

- **覆盖性**：service_name、summary、hypotheses、suggestions 非空检查
- **可复现性**：query_key/correlation_id 但结论泛化时标记 needs_extra
- **一致性**：勘探证据充足但结论泛化时标记 needs_extra
- **安全性**：redact_sensitive 脱敏 AK/SK、token、连接串
- **追加工具**：needs_extra 时最多追加 0~2 次 tool calls（correlation.get_info、index.get_status）

### 2.3 Act 阶段

- **可复现参数**：correlation.get_info、index.get_status 截断时追加 `【可复现参数】query_key=xxx, trace_id=xxx`
- **重复读取优化**：code.read 同文件多次读取时，保留最后一次，其余替换为占位
- **多级截断**：`_truncate_multilevel` 按接近上限程度选择 half/quarter
- **上下文压缩**：轮数≥5 或字符数>40k 时压缩 prev_tool_results

---

## 三、配置与兼容

### 3.1 新增配置

```yaml
# AI 驱动
ai_driven_enabled: true        # 默认 true，优先走 AI 驱动
max_analysis_rounds: 20       # 多轮迭代上限
analysis_timeout_seconds: 160 # 与 JobQueue 对齐

# Hook
hooks:
  enabled: true
  dirs: ["data/hooks"]

# MCP 外部 Server
mcp:
  servers:
    aliyun:
      transport: streamable-http
      url: http://localhost:8080/mcp
```

### 3.2 向后兼容

- `/ingest`、`/ingest/aliyun-sls`、`/index/status` 等 API 行为不变
- `cfg.llm` 旧配置仍兼容，AiGateway 自动创建 provider
- 直连路径保留，AI 驱动失败时自动回退

---

## 四、文档索引

| 文档 | 说明 |
|------|------|
| [Hook体系说明.md](Hook体系说明.md) | Hook 使用说明 |

---

## 五、升级建议

1. **首次启用**：确认 `config.yaml` 中 `ai_driven_enabled: true`（默认已启用）
2. **LLM 配置**：确保 `llm` 或 `ai.providers` 已配置 api_key
3. **可选**：配置 `hooks.dirs` 添加自定义 Hook 脚本
4. **可选**：接入外部 MCP Server 扩展工具能力
