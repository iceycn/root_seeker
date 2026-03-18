# RootSeeker v3.0.0 更新说明

## 概述

v3.0.0 在 v2.0.0 基础上新增两大重点：

1. **外部依赖识别升级**：支持 Java（Maven/Gradle）、Python（requirements/pyproject/pip freeze）等依赖识别与版本解析
2. **AI 代码解析能力升级**：参考 Cursor/Trae/Cline 的 IDE 上下文管理策略，优化「先勘探、再定位、再综合」的分析质量

### Cline 参考对齐（基于 cline-3.72.0 源码核对）

| 设计点 | Cline 3.72.0 | RootSeeker v3.0.0 |
|--------|--------------|-------------------|
| 工具错误回写 | tool_result 直接 push 进 conversation，主 LLM 下一轮自行修正 | 专门的「错误判断 AI」分析并输出 corrected_args 后重试 |
| 渐进式错误 | writeToFileMissingContentError 按 1/2/3+ 次分级（仅 write_to_file content 缺失） | 所有工具 failure_count 分级提示 |
| 缺参错误 | missingToolParameterError(paramName) 明确标出参数名 | format_tool_error 含 error_code，可扩展 paramName |
| 统一错误格式 | formatResponse.toolError() 含 `<error>` 标签 | format_tool_error() 含 `<error>` 标签 |
| mistake_limit | 达上限 ask 用户 feedback，tooManyMistakes 后继续 | 达上限中止分析，回退直连 |

详见 [提示词计划_v3.0.0.md](提示词计划_v3.0.0.md)。

---

## 一、新增 MCP 工具

### 1.1 外部依赖识别

| 工具 | 说明 |
|------|------|
| `deps.parse_external` | 解析 pom.xml/build.gradle/requirements.txt/pyproject.toml，输出结构化依赖画像（ecosystem、direct_dependencies、risk_flags） |
| `deps.diff_declared_vs_resolved` | 对比声明与解析的依赖，输出漂移项（声明有但未解析、解析有但未声明、版本不一致） |
| `cmd.run_build_analysis` | 安全执行 mvn dependency:tree / gradle dependencies / pip freeze，仅白名单映射，禁止任意 Shell 注入 |

### 1.2 依赖源码兜底

| 工具 | 说明 |
|------|------|
| `deps.fetch_java_sources` | 获取 Java 依赖的源码坐标并物化到 ~/.m2 中的 *-sources.jar |
| `deps.index_dependency_sources` | 对已物化源码建立索引，供 code.resolve_symbol 使用 |
| `code.resolve_symbol` | 当 LSP 不可用时，基于 code.search 在仓库中定位符号定义 |

---

## 二、服务层

### 2.1 external_deps

- `parse_maven_pom` / `parse_gradle_build` / `parse_python_manifest`：静态解析构建文件
- `parse_external`：自动检测并解析
- `diff_declared_vs_resolved`：声明 vs 解析漂移对比

### 2.2 dependency_sources

- `fetch_java_sources`：从构建文件解析依赖坐标
- `materialize_maven_sources`：查找 ~/.m2 中的 *-sources.jar
- `index_source_roots`：索引物化源码（占位，供后续扩展）

---

## 三、纠偏优化

### 3.0 工具错误与参数修正（Cline 参考）

- 提示词计划已补充 Cline 3.72.0 工具错误处理参考：统一错误格式、渐进式错误、参数修正策略、mistake_limit
- 对比分析 Prompt 中 B 项已细化 Cline 工具错误处理流程（pushToolResult、writeToFileMissingContentError、missingToolParameterError、mistake_limit）
- **代码实现**（参考 Cline 异常处理模式）：
  - `format_response.py`：按 error_code 差异化错误格式化（format_tool_timeout_error、format_dependency_unavailable_error、format_tool_not_found_error）；INVALID_PARAMS 时显式标出 param_name；新增 UNRECOVERABLE_ERROR_CODES（TOOL_NOT_FOUND、DEPENDENCY_UNAVAILABLE）
  - `orchestrator.py`：不可修正错误码跳过错误判断 AI；渐进式错误第 3+ 次附加策略建议（简化参数、abort）
  - `prompts.py`：FIX_ARGS 提示词增强，INVALID_PARAMS 时优先补全错误信息中已标明的参数名

### 3.1 上下文发现

- **关键行优先采样**：`discover_refs_from_error_log` 不再仅取前 2000 字，改为优先采样含 trace_id、stacktrace、Exception、at com. 等关键信号的行
- **截断提示**：采样截断时在 hints 中标注，避免 Plan 误判「没有 trace_id」

### 3.2 Orchestrator

- **静默异常可观测**：`except Exception: pass` 改为至少记录 analysis_id、tool_name、exception_class
- **repo_id 注入**：`deps.parse_external`、`cmd.run_build_analysis` 支持从 context 自动注入 repo_id
- **tool_use_loop 模式**（Cline/Cursor 风格）：`OrchestratorConfig(orchestration_mode="tool_use_loop")` 时，由模型自主决定何时调用工具、何时输出 JSON 报告；无 tool_use 即结束。需 LLM 支持 `generate_with_tools`。

### 3.3 Prompt

- 错误涉及依赖冲突（ClassNotFound/NoSuchMethodError/ImportError）时，可先 `deps.parse_external`，必要时再 `cmd.run_build_analysis`

---

## 四、触发策略（写入 Prompt）

- **默认**：先调用 `deps.parse_external`
- **动态解析**：仅当版本变量无法解析、存在 BOM/多配置、或问题明确与运行态依赖冲突相关时，才调用 `cmd.run_build_analysis`
- **依赖代码定位**：优先 `code.resolve_symbol`（基于 Zoekt）；LSP 能力待后续实现

---

## 五、本轮新增（续）

### 5.1 Orchestrator 结构感知截断

- 对 code.search、correlation.get_info、evidence.context_search 等 JSON 类结果，保留关键字段、截断 preview
- 截断时附加 `[truncation_meta: is_truncated=true, original_length=N]` 供 LLM 感知

### 5.2 相关性保留压缩

- 压缩时保留「首次定位证据」（第一个含 file_path 的 code.search/code.read）+ 最近 N 个
- 避免仅保留最近 N 个导致首次定位证据丢失

### 5.3 Service graph 扩展

- 新增依赖线索：`lb://service`、Feign `value`/`url`、占位符 `${...}`（低置信度）
- 扫描超限时写入 `scan_meta.risk_flags`，deps.get_graph 输出中可见

### 5.4 Call graph 可观测

- Tree-sitter 回退到正则时记录 `treesitter_fallback`
- Zoekt 搜索失败时记录 `zoekt_failed`
- 扫描文件数达 200 上限时记录 `scan_truncated`
- 降级信息写入 evidence.notes 的 `[degraded_modes]`、`[risk_flags]`

---

## 六、待实现（后续版本）

- **Headless LSP**：lsp.start/stop/workspace_symbol/definition/references，需 JDT LS、Pyright 等外部依赖
