# Cline 参考：上下文发现与 MCP 流程

参考 [cline-dev/cline](https://github.com/cline-dev/cline) 3.72.0 的架构，用于优化 RootSeeker 的上下文发现、AI 驱动与 MCP 使用流程。

## 1. Cline 核心设计

### 1.1 上下文发现（loadContext）

```
用户输入 (含 @file、@folder、slash 命令)
    ↓
parseMentions() → 解析 @ 引用，替换为文件/目录内容
    ↓
parseSlashCommands() → 处理 / 命令、规则、工作流
    ↓
processContentBlock() → 处理 tool_result 中的 mention
    ↓
getEnvironmentDetails() → 环境信息（可见文件、打开标签、终端）
    ↓
RuleContextBuilder.buildEvaluationContext() → 规则条件（paths、tabs 等）
```

- **上下文来源**：用户消息、可见/打开标签、工具结果、工具请求（ask="tool"）
- **规则**：`RuleContextBuilder` 从 `clineMessages` 提取路径、标签等，用于规则激活

### 1.2 AI 驱动主循环（attemptApiRequest）

```
1. 前置检查（mistake limit、checkpoint 等）
2. ContextManager.shouldCompactContextWindow() → 是否需 compact
3. loadContext() → 加载上下文、解析 mentions、slash 命令
4. addToApiConversationHistory()
5. API 流式请求（streamMessage）
6. 流式处理：解析 tool_use → processNativeToolCalls()
7. toolExecutor.executeTool(block) → 执行工具
8. 若为 MCP 工具 → UseMcpToolHandler.execute() → mcpHub.callTool()
9. 将 tool_result 加入 conversation history
10. 循环：若仍有 tool_use，继续请求 API
```

### 1.3 MCP 工具发现与调用

**发现：**

```
McpHub 初始化
    ↓
readAndValidateMcpSettingsFile() → 读取 MCP 配置
    ↓
connectToServer() → 建立连接（stdio/sse/streamableHttp）
    ↓
fetchToolsList() → tools/list
fetchResourcesList() → resources/list
fetchPromptsList() → prompts/list
    ↓
connection.server.tools 等缓存
    ↓
subscribeToMcpServers() → gRPC 推送给订阅者
```

**调用：**

```
ClineToolSet.getNativeTools() → 合并 Cline 工具 + MCP 工具
    ↓
mcpToolToClineToolSpec() → 转为 ClineToolSpec，命名格式：serverUid + CLINE_MCP_TOOL_IDENTIFIER + toolName
    ↓
系统提示中注入工具列表
    ↓
模型返回 tool_use 块
    ↓
ToolExecutorCoordinator 路由到 UseMcpToolHandler
    ↓
McpHub.callTool(serverName, toolName, arguments) → tools/call RPC
```

### 1.4 工具文档注入（loadMcpDocumentation）

Cline 在系统提示中注入 MCP 相关文档，帮助模型理解如何创建/使用 MCP Server。RootSeeker 借鉴此思路，在 Plan 阶段注入**工具参数概要**（名称+描述+参数类型/必填）。

## 2. RootSeeker 已实现的优化

### 2.1 上下文发现（context_discovery.py）

| Cline | RootSeeker 实现 |
|-------|-----------------|
| parseMentions | `discover_refs_from_error_log()`：从 error_log 提取 trace_id、类名/方法名、配置项、error_code |
| getEnvironmentDetails | `_discover_context()`：预取 index.get_status、correlation.get_info（若有 trace_id） |
| 规则条件 | `build_hints_for_plan()`：根据引用生成 Plan 提示 |

### 2.2 AI 驱动流程

| Cline | RootSeeker |
|-------|------------|
| loadContext 在每次请求前 | `_discover_context()` 在首轮 Plan 前 |
| 工具结果回写 conversation | tool_results 传给 Synthesize |
| 流式 tool_use 循环 | Plan→Act→Synthesize→Check 多轮迭代 |

### 2.3 MCP 发现与使用

| Cline | RootSeeker |
|-------|------------|
| McpHub 连接 + tools/list 缓存 | McpGateway.startup() + list_tools() |
| ClineToolSet 合并工具 | 内部工具 + 外部 MCP 会话，build_tools_summary() |
| 工具文档注入 | `_build_tool_schema_doc()`：名称+描述+参数概要 |
| 外部工具命名前缀 | ExternalMcpSession 支持 prefix（server_id） |

## 3. 关键文件

| 用途 | RootSeeker 路径 |
|------|-----------------|
| 上下文发现 | `root_seeker/ai/context_discovery.py` |
| AI 编排 | `root_seeker/ai/orchestrator.py` |
| MCP 网关 | `root_seeker/mcp/gateway.py` |
| 提示词 | `root_seeker/prompts.py` |

## 4. 后续可借鉴点（简要）

1. ~~**上下文截断**~~：✅ 已实现（`_should_compact_context` + `_compact_tool_results`，轮数/字符数超阈值时压缩 prev_tool_results）
2. ~~**Hook 缓存**~~：✅ 已实现（完整 Cline 式 Hook 体系：HookDiscoveryCache + HookHub + 四种 Hook 类型）
3. ~~**外部工具命名**~~：✅ 已实现（`MCP_TOOL_IDENTIFIER = "."`，`server_id + . + tool_name`）

---

## 5. 可进一步借鉴的设计点（详细）

### 5.1 上下文管理（ContextManager）— 高优先级

| 设计点 | Cline 实现 | root_seek 差距 | 借鉴价值 |
|--------|------------|----------------|----------|
| **多级截断策略** | `getNextTruncationRange()`：half（保留 50%）、quarter（保留 25%），始终保留首条 user-assistant 对 | 仅有 `_truncate_text()` 单次截断 | 长对话时按 token 压力选择截断强度 |
| **重复文件优化** | `getPossibleDuplicateFileReads()`：同一文件多次 read_file 时，保留最后一次，其余替换为 `duplicateFileReadNotice()` 占位 | 无 | 对 code.read 多次读取同一 file_path 做去重，减少 token |
| **tool_use/tool_result 配对** | `ensureToolResultsFollowToolUse()`：缺失时补 `"result missing"` | Plan→Act 顺序执行，无缺失 | 若引入流式 tool_use 可借鉴 |
| **content-limits** | `truncateContent()` 对超长内容截断并附带说明 | `_truncate_text()` 无说明 | 截断时加 `...[截断，原长 N 字]...` |

### 5.2 工具执行（ToolExecutor）— 中优先级

| 设计点 | Cline 实现 | root_seek 差距 | 借鉴价值 |
|--------|------------|----------------|----------|
| **渐进式错误** | `writeToFileMissingContentError()`：按连续失败次数（1/2/3+）给出不同提示 | 无 | 同一工具连续失败时，提示更具体（如「第 3 次失败，建议检查参数」） |
| **统一错误格式** | `formatResponse.toolError()` 结构化错误文案 | `ToolResult.error()` 简单文本 | 错误格式统一，便于 AI 理解 |
| **Plan 模式限制** | `PLAN_MODE_RESTRICTED_TOOLS` 限制 write_to_file 等 | 无 Plan 模式 | 若引入 plan-only 阶段可限制写操作 |

### 5.3 MCP 高级（McpHub）— 高优先级

| 设计点 | Cline 实现 | root_seek 差距 | 借鉴价值 |
|--------|------------|----------------|----------|
| **StreamableHTTP 重连** | `StreamableHttpReconnectHandler`：指数退避（2s×2^attempt），最多 6 次 | `ExternalMcpSession` 连接失败即放弃 | streamable-http 断线时自动重连 |
| **notifications** | `pendingNotifications` + `notificationCallback` 推送给当前 task | 无 | 接收 MCP 通知并展示 |
| **resources/prompts** | `resources/list`、`prompts/list` 暴露给 UI | 无 | 若需 MCP 资源/提示列表可扩展 |

### 5.4 流式处理（StreamChunkCoordinator）— 中优先级（若需流式）

| 设计点 | Cline 实现 | root_seek 差距 | 借鉴价值 |
|--------|------------|----------------|----------|
| **usage/content 分流** | usage 立即 `onUsageChunk` 更新 token/cost，content 入队 | 无流式 | 接入流式 API 时单独处理 usage |
| **流式 tool_use 解析** | `JSONParser` 增量解析 + `extractPartialJsonFields()` 兜底 | 无 | 流式解析 tool_use 块 |
| **partial tool_use 展示** | `getPartialToolUsesAsContent()` | 无 | 流式过程中展示 partial |

### 5.5 规则/技能（RuleContextBuilder、skills）— 中优先级

| 设计点 | Cline 实现 | root_seek 差距 | 借鉴价值 |
|--------|------------|----------------|----------|
| **RuleContextBuilder** | 从用户消息、可见 tabs、工具结果、待执行工具提取路径，用于规则激活 | 无 | 从 tool_results 提取 file_path、repo_id 等，用于规则/条件判断 |
| **apply_patch 路径解析** | 从 patch 头部提取 `*** Add File: path` | 无 patch 工具 | 若引入 patch 类工具可借鉴 |
| **skills/workflows** | `.agents/skills`、slash commands 激活 | 无 | 按需引入技能/工作流体系 |

### 5.6 提示词构建（PromptBuilder）— 中优先级

| 设计点 | Cline 实现 | root_seek 差距 | 借鉴价值 |
|--------|------------|----------------|----------|
| **SystemPromptContext** | 强类型上下文：providerInfo、cwd、mcpHub、skills 等 | 各模块直接 `format()` 字符串 | 用 dataclass 承载上下文，便于扩展 |
| **组件化** | `getObjectiveSection`、`getRulesSection`、`getToolUseSection` 独立组件 | `prompts.py` 为扁平字符串模板 | 按 section 拆分，便于维护 |
| **postProcess** | 合并空行、去除空 section | ~~无~~ ✅ 已实现 | `_post_process` 合并空行 + 去除仅含「标签：」的空块 |

### 5.7 其他（checkpoint、mistake limit）— 低优先级

| 设计点 | Cline 实现 | root_seek 差距 | 借鉴价值 |
|--------|------------|----------------|----------|
| **mistake limit** | `mistake_limit_reached`、`tooManyMistakes()` | 无 | 连续工具失败 N 次时停止并提示 |
| **checkpoint** | git 分支式 checkpoint | 无 | 若需可回滚可引入 |
| **focus chain** | 任务进度清单（checklist） | 无 | 若需任务拆解可借鉴 |

---

## 6. 建议优先实施顺序

1. ~~**MCP StreamableHTTP 重连**~~：✅ 已实现（`ExternalMcpSession` 指数退避 + call_tool 连接错误时重连）
2. ~~**重复工具结果优化**~~：✅ 已实现（`_optimize_duplicate_tool_results`）
3. ~~**多级截断策略**~~：✅ 已实现（`_truncate_multilevel`）
4. ~~**渐进式工具错误**~~：✅ 已实现（`_call_tool_with_retry` 的 `failure_count` + 分级提示）
5. ~~**PromptBuilder / SystemPromptContext**~~：✅ 已实现（`AIPromptContext` + `AIPromptBuilder` + `build_*_prompt`）
6. ~~**MCP 连接等待**~~：✅ 已实现（`ensure_mcp_ready`）
7. ~~**mistake_limit**~~：✅ 已实现（`OrchestratorConfig.mistake_limit`，同一工具连续失败 N 次中止）
8. ~~**LLM 自动重试**~~：✅ 已实现（`_llm_generate_with_retry`，指数退避 2s×2^attempt）

---

## 7. 中低优先级已实现

| 设计点 | 实现 |
|--------|------|
| **统一错误格式** | `mcp/format_response.py`：`format_tool_error()`、`format_too_many_mistakes()`，含 `<error>` 标签 |
| **RuleContextBuilder** | `ai/rule_context.py`：`extract_paths_from_tool_results()` 从 code.search/code.read 提取路径，注入下一轮 Plan |
| **MCP resources/prompts** | `ExternalMcpSession.list_resources()`、`list_prompts()`；`McpGateway.list_resources()`、`list_prompts()` |
| **提示词组件化** | `prompt_builder.py`：`get_objective_section()`、`get_rules_section()`、`get_tools_section()`、`build_plan_system_from_components()` |
| **focus chain** | `build_focus_chain()`：任务进度清单（获取上下文→定位代码→收集证据→分析根因），注入 Plan |
| **checkpoint** | `OrchestratorConfig.checkpoint_enabled`：每轮决策后 audit 记录 checkpoint |
| **Plan 模式限制** | `PLAN_RESTRICTED_TOOLS` 常量，Plan 阶段过滤受限工具（当前为空，可配置 write 类工具） |
| **shouldCompactContextWindow** | `_should_compact_context()` + `_compact_tool_results()`：轮数≥5 或字符数>40k 时压缩 prev_tool_results |
| **MCP_TOOL_IDENTIFIER** | `external_client.py`：`MCP_TOOL_IDENTIFIER = "."`，外部工具命名 `server_id.tool_name` |
| **postProcess 去除空 section** | `_post_process()`：去除仅含「标签：」的空块 |
| **完整 Hook 体系** | `hooks/`：AnalysisStart、AnalysisComplete、PreToolUse、PostToolUse；HookDiscoveryCache；config.hooks |
