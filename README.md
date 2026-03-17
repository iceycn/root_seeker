# RootSeeker

<p align="center">
    <img src="https://img.shields.io/badge/version-3.0.0-blue.svg" alt="Version">
    <img src="https://img.shields.io/badge/python-3.11+-blue.svg" alt="Python Version">
    <img src="https://img.shields.io/badge/license-Apache-green.svg" alt="License">
    <img src="https://img.shields.io/badge/docker-ready-blue.svg" alt="Docker">
</p>

<p align="center">
  <strong><a href="README.md">中文</a></strong> | <strong><a href="README.en.md">English</a></strong>
</p>

**RootSeeker** 是一个面向公司内网的 **AI 驱动错误分析与根因发现服务**。它帮你**告别「通灵」式 Debug**：从一条报错日志出发，自动还原故障现场、定位问题代码、生成专家级修复建议，像人类专家一样逐步逼近根因。

**核心价值**：将研发人员从繁杂的证据收集中解放出来，借助 AI 快速定位根因、缩短排查时长，减少现网应急带来的损失。AI 自主规划工具调用、收集证据、多轮推理，在 30 秒内产出可落地的根因报告。支持私有化部署，代码与日志不出内网。

**使用它能带来什么**：不再对着堆栈瞎猜；自动关联 TraceID 拉取全链路上下文（API 入参、SQL、RPC）；构建私有代码索引，语义搜索理解业务意图；分析报告实时推送至企微/钉钉，节省排查时间、提升故障响应效率。

v3.0.0 支持 **Plan-Act** 与 **tool_use_loop** 双编排模式，通过 **MCP 网关**、**SLS**、**Zoekt**、**Qdrant** 和 **LLM** 协同，实现自动化的根因发现。

> **如果觉得这个项目对你有帮助，请帮忙点个 Star ⭐️，你的支持是我们更新的动力！**

> 📮 **项目快速迭代中**：如果您有任何需求或建议，欢迎通过 [Issue](https://gitee.com/icey_1/root_seeker/issues) 提交，我们会优先考虑您的反馈。也可联系：**wuhun0301@qq.com**

---

## 📚 目录

- [为什么选择 RootSeeker？](#-为什么选择-rootseeker)
- [核心特性](#-核心特性)
- [v3.0.0 架构](#-v300-架构)
  - [Plan-Act 与 tool_use_loop 区别](#plan-act-与-tool_use_loop-区别)
- [工作原理](#-工作原理)
- [快速开始](#-快速开始)
- [配置说明](#-配置说明)
- [部署文档](#-部署文档)
- [API 参考](#-api-参考)
- [案例分析](#-案例分析)
- [贡献指南](#-贡献指南)
- [License](#-license)

---

## 🚀 为什么选择 RootSeeker？

传统的故障排查往往依赖人工经验，SRE 需要在日志平台、监控系统和 IDE 之间反复横跳，耗时耗力。RootSeeker 旨在解决以下痛点：

*   **告别“通灵”式 Debug**：不再对着报错堆栈瞎猜，直接定位到具体的代码行。
*   **全息现场还原**：自动关联 TraceID，拉取同一链路上的所有上下文日志（API 入参、SQL、RPC）。
*   **懂你的私有代码**：构建私有代码索引，即使是复杂的业务逻辑，AI 也能通过语义搜索理解意图。
*   **多轮侦探推理**：AI 自主规划工具调用顺序，通过多轮追问和二次检索，逐步逼近根因。

---

## ✨ 核心特性

- **🤖 AI 驱动主流程**：Plan → Act → Synthesize → Check 多轮迭代；可选 tool_use_loop 由模型自主 tool call。
- **🔌 MCP 网关**：应用内极简网关，工具注册/发现/执行；支持外部 MCP Server（stdio/streamable-http）扩展。
- **🔍 双引擎代码检索**：结合 Zoekt（正则/符号）和 Qdrant（向量语义），兼顾精确匹配与意图理解。
- **📦 evidence.context_search**：在已收集证据上下文中检索，避免重复调用 code.search/correlation，节省 token。
- **🔗 全链路日志补全**：自动从阿里云 SLS 等源拉取上下文，还原故障发生时的完整数据流。
- **📡 多渠道触达**：分析报告实时推送至企业微信、钉钉，支持 Markdown 格式。
- **🛡️ 数据安全**：支持私有化部署，代码和日志不出内网（可对接本地 LLM）。
- **🪝 Hook 体系**：AnalysisStart、PreToolUse、PostToolUse 等，支持自定义脚本注入分析生命周期。

---

## 🆕 v3.0.0 架构

v3.0.0 在 v2.0.0 基础上新增 **tool_use_loop 模式**、**外部依赖识别** 与 **链路追问** 等能力，支持双编排模式与更细粒度的证据收集。

### MCP 工具

| 工具 | 说明 | 价值 |
|------|------|------|
| `index.get_status` | 获取仓库与索引概览 | 避免盲目猜测 repo_id，先了解代码结构再规划检索，减少无效调用 |
| `correlation.get_info` | 获取关联日志、Trace 链 | 还原故障现场完整数据流（API 入参、SQL、RPC），从单条错误扩展到全链路上下文 |
| `code.search` | Zoekt 正则/关键词代码搜索 | 从堆栈/类名快速定位到具体文件与行号，替代人工逐文件搜索 |
| `code.read` | 读取文件内容 | 获取完整实现细节，支持行号范围，避免仅靠片段臆断根因 |
| `evidence.context_search` | 在已收集证据中检索 | 避免重复调用 code.search/correlation，节省 token 与延迟，提升多轮分析效率 |
| `deps.get_graph` | 依赖拓扑、调用链 | 识别上下游影响面，ClassNotFound/NoSuchMethodError 时定位依赖冲突 |
| `deps.parse_external` | 解析 pom/gradle/requirements 依赖 | 静态分析声明依赖与版本，识别依赖冲突、版本漂移风险 |
| `code.resolve_symbol` | 定位符号定义（LSP 不可用时） | 依赖库内符号定位兜底，支持 jdt://、dep_cache 等路径 |
| `analysis.synthesize` | 基于证据生成报告 | 将多源证据统一推理为根因结论与修复建议 |
| `analysis.run` / `analysis.run_full` | 全量分析（兜底） | 无勘探需求时一站式执行，保证分析可用性 |

### Plan-Act 与 tool_use_loop 区别

| 对比项 | Plan-Act | tool_use_loop |
|--------|----------|----------------|
| **流程** | 每轮固定四步：Plan（规划）→ Act（批量执行）→ Synthesize（生成报告）→ Check（自检 + 下一轮决策） | 模型自主决定：每次 LLM 调用可选择是否调用工具、调用哪些工具，直到不再输出 tool_use 时直接输出 JSON 报告 |
| **控制权** | 应用层控制流程，模型负责「规划」与「综合」 | 模型自主控制，流式 tool call 循环（call → 执行 → 结果回写 → 再次请求 → 循环直到结束） |
| **适用场景** | 需要结构化、可预测的多轮迭代；对不支持原生 tool calling 的 LLM 友好 | 需要模型更灵活地「边探索边决策」；需 LLM 支持 `generate_with_tools` |
| **配置** | `orchestration_mode: "plan_act"`（默认） | `orchestration_mode: "tool_use_loop"` |

### AI 驱动流程（Plan-Act 模式）

```
Plan（规划）→ Act（执行工具）→ Synthesize（生成报告）→ Check（自检 + 下一轮决策）
         ↑                                                              ↓
         └────────────── 若需更多证据，继续下一轮 ←─────────────────────┘
```

- **勘探优先**：细粒度工具（index/correlation/code.search/evidence.context_search/code.read）优先于全量 analysis.run。
- **失败回退**：任意 tool 失败或 Plan 解析失败时自动回退到直连路径，保证分析可用性。
- **上下文发现**：Plan 前预取 index/correlation，从 error_log 解析 trace_id、类名、方法名注入提示。

### AI 网关与 Hook

- **AI 网关**：动态切换/新增 LLM 配置（DeepSeek、豆包等），api_key 支持 `ENV:VAR_NAME` 引用。
- **Hook 体系**：`~/.rootseek/hooks/` + `config.hooks.dirs`，支持 AnalysisStart、AnalysisComplete、PreToolUse、PostToolUse。

### v3.0.0 重大更新

| 更新 | 说明 |
|------|------|
| **tool_use_loop 模式** | 模型自主决定何时调用工具、何时输出 JSON，`config.orchestration_mode: "tool_use_loop"` 启用 |
| **外部依赖识别** | `deps.parse_external`、`deps.diff_declared_vs_resolved`、`cmd.run_build_analysis`，支持 Java/Python 依赖解析与漂移检测 |
| **链路追问** | 发现「集合为空」「数据缺失」等中间结论时，自动输出 NEED_MORE_EVIDENCE 追溯上游，避免过早收尾 |
| **上下文发现对齐** | 工具错误分级提示、mistake_limit、结构感知截断、相关性保留压缩 |
| **依赖源码兜底** | `code.resolve_symbol`、`deps.fetch_java_sources`，LSP 不可用时仍可定位依赖库符号 |

详见 [docs/CHANGELOG_v3.0.0.md](docs/CHANGELOG_v3.0.0.md)、[docs/提示词计划_v3.0.0.md](docs/提示词计划_v3.0.0.md)。

---

## 🛠️ 工作原理

```mermaid
graph TB
    subgraph 数据摄入
        Log["错误日志 (SLS)"] --> Ingest["/ingest"]
        Ingest --> Queue["任务队列"]
    end

    subgraph AI 驱动分析
        Queue --> Plan["Plan: AI 规划工具"]
        Plan --> Act["Act: 执行 MCP 工具"]
        Act --> Enrich["日志补全"]
        Act --> Zoekt["Zoekt 检索"]
        Act --> Qdrant["Qdrant 检索"]
        Enrich --> Context["构建上下文"]
        Zoekt --> Context
        Qdrant --> Context
        Context --> Synthesize["Synthesize: LLM 生成报告"]
        Synthesize --> Check["Check: 自检 + 下一轮决策"]
        Check -->|需更多证据| Plan
        Check -->|完成| Report["分析报告"]
    end

    Report --> Notify["企微/钉钉通知"]
```

1.  **Ingest**：接收报错，入队分析任务。
2.  **Plan**：AI 规划本轮要调用的工具（index/correlation/code.search/evidence.context_search/code.read 等）。
3.  **Act**：执行器按计划调用 MCP 工具，收集证据。
4.  **Synthesize**：将工具结果转为证据，LLM 生成本轮报告。
5.  **Check**：自检覆盖性、一致性、可复现性；若需更多证据，AI 决策下一轮 Plan。
6.  **Report**：生成包含根因、证据和修复建议的最终报告。

---

## 🏁 快速开始

### 环境要求

| 组件 | 版本要求 | 说明 |
|------|----------|------|
| **Python** | ≥ 3.11 | 核心服务 |
| **JDK** | 8 | Admin 管理后台 |
| **Docker** | 20+ | 推荐部署方式 |

### 一键部署 (Docker)

```bash
# 1. 克隆仓库
git clone https://gitee.com/icey_1/root_seeker.git
cd root_seeker/root_seeker_docker

# 2. 启动服务 (自动处理配置)
bash start.sh
```

启动后访问：
*   **RootSeeker API**: `http://localhost:8000`
*   **Admin 后台**: `http://localhost:8080`

### 手动安装 (macOS/Linux)

```bash
# 1. 复制配置
cp config.example.yaml config.yaml

# 2. 安装依赖
bash scripts/install-without-docker.sh

# 3. 启动所有服务
bash scripts/start-all-one-click.sh
```

---

## ⚙️ 配置说明

### 启用 AI 驱动（默认）

```yaml
# config.yaml
ai_driven_enabled: true   # 默认 true，优先走 AI 驱动
orchestration_mode: "plan_act"   # plan_act（Plan→Act→Synthesize）| tool_use_loop（需 LLM 支持 generate_with_tools）
max_analysis_rounds: 20  # 多轮迭代上限
```

### LLM 配置

```yaml
llm:
  kind: deepseek
  base_url: "https://api.deepseek.com"
  api_key: "ENV:DEEPSEEK_API_KEY"  # 支持环境变量引用
  model: "deepseek-chat"
```

### Hook（可选）

```yaml
hooks:
  enabled: true
  dirs: ["data/hooks"]  # 额外 Hook 目录
```

脚本放置于 `~/.rootseek/hooks/` 或 `config.hooks.dirs`，详见 [Hook体系说明.md](docs/Hook体系说明.md)。

---

## 📖 部署文档

| 文档 | 说明 |
|------|------|
| [配置参考](docs/components/00-配置参考.md) | `config.yaml` 全解 |
| [阿里云 SLS 集成](docs/components/03-阿里云SLS.md) | 日志源配置 |
| [LLM 配置](docs/components/04-LLM配置.md) | DeepSeek/OpenAI/豆包接入 |
| [通知配置](docs/components/07-通知配置.md) | 企微/钉钉机器人 |
| [v3.0.0 更新说明](docs/CHANGELOG_v3.0.0.md) | tool_use_loop、外部依赖识别、链路追问 |
| [v2.0.0 更新说明](docs/CHANGELOG_v2.0.0.md) | MCP 网关、AI 驱动、Hook 体系 |
| [Hook 体系](docs/Hook体系说明.md) | 分析生命周期自定义脚本 |
| [文档索引](docs/文档索引.md) | 更多文档 |

---

## 🔌 API 参考

| 接口 | 方法 | 说明 |
|------|------|------|
| `/ingest` | POST | 提交错误日志进行分析 |
| `/ingest/aliyun-sls` | POST | 接收 SLS Webhook 回调 |
| `/analysis/{id}` | GET | 查询分析报告结果 |
| `/mcp/tools` | GET | 列出 MCP 工具 |
| `/mcp/call` | POST | 执行 MCP 工具 |
| `/git-source/repos` | GET | 获取仓库列表 |
| `/index/status` | GET | 索引状态 |

更多接口请查看 Swagger UI：`http://localhost:8000/docs`。

---

## 💡 案例分析

> **场景**：线上交易服务突发 `NullPointerException`。
>
> **RootSeeker v3.0.0 的表现**：
> 1.  **Plan**：AI 规划先调用 index.get_status、correlation.get_info 获取上下文，再 code.search 定位 DiscountCalculator。
> 2.  **Act**：执行器按计划调用工具，Zoekt 定位到 `DiscountCalculator.java` 第 89 行，Qdrant 发现该类新增了 `@Autowired private VipStrategy vipStrategy;`。
> 3.  **Synthesize**：LLM 结合日志与代码证据，指出该类由 `new` 手动实例化，导致 Spring 注入失败。
> 4.  **Check**：自检通过，输出最终报告。
> 5.  **报告**：30 秒内推送至企微/钉钉，建议改为 Spring 托管或构造函数注入。

---

## 🤝 贡献指南

欢迎提交 Pull Request 或 Issue！

1.  Fork 本仓库
2.  新建 Feat_xxx 分支
3.  提交代码
4.  新建 Pull Request

---

## 📄 License

Apache 2.0 License © 2026 RootSeeker Team

---

**如果这个项目帮到了你，请给一个 Star ⭐️ 支持一下！**
