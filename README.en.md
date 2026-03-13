# RootSeeker

<p align="center">
    <img src="https://img.shields.io/badge/version-2.0.0-blue.svg" alt="Version">
    <img src="https://img.shields.io/badge/python-3.11+-blue.svg" alt="Python Version">
    <img src="https://img.shields.io/badge/license-Apache-green.svg" alt="License">
    <img src="https://img.shields.io/badge/docker-ready-blue.svg" alt="Docker">
</p>

<p align="center">
  <strong><a href="README.md">中文</a></strong> | <strong><a href="README.en.md">English</a></strong>
</p>

**RootSeeker** is an **AI-driven error analysis and root cause discovery service** for internal company networks. v2.0.0 upgrades the main flow to **Plan → Act → Synthesize → Check** multi-round iteration, where the AI autonomously decides which tools to call and which evidence to collect, approaching the root cause step by step like a human expert.

By integrating **MCP Gateway**, **SLS (Logs)**, **Zoekt (Exact Code Search)**, **Qdrant (Semantic Vector Search)**, and **LLM (Large Model Reasoning)**, RootSeeker automatically reconstructs the failure scene, locates problematic code, and generates expert-level repair suggestions.

> **If this project helps you, please give it a Star ⭐️, your support is our motivation!**

> 📮 **Rapid iteration**: If you have any needs or suggestions, please submit via [Issues](https://gitee.com/icey_1/root_seeker/issues). We prioritize your feedback. Contact: **wuhun0301@qq.com**

---

## 📚 Table of Contents

- [Why Choose RootSeeker?](#-why-choose-rootseeker)
- [Key Features](#-key-features)
- [v2.0.0 Architecture](#-v200-architecture)
- [How It Works](#-how-it-works)
- [Quick Start](#-quick-start)
- [Configuration](#-configuration)
- [Deployment Docs](#-deployment-docs)
- [API Reference](#-api-reference)
- [Case Study](#-case-study)
- [Contributing](#-contributing)
- [License](#-license)

---

## 🚀 Why Choose RootSeeker?

Traditional troubleshooting often relies on manual experience, requiring SREs to switch back and forth between log platforms, monitoring systems, and IDEs, which is time-consuming and laborious. RootSeeker aims to solve the following pain points:

*   **Goodbye "Psychic" Debugging**: No more guessing at error stacks; directly locate specific code lines.
*   **Holographic Scene Reconstruction**: Automatically associate TraceIDs and pull all contextual logs (API inputs, SQL, RPC) on the same link.
*   **Understands Your Private Code**: Builds a private code index, allowing AI to understand intent via semantic search even for complex business logic.
*   **Multi-turn Detective Reasoning**: AI autonomously plans tool call order, gradually approaching the root cause through multi-turn questioning and secondary retrieval.

---

## ✨ Key Features

- **🤖 AI-Driven Main Flow**: Plan → Act → Synthesize → Check multi-round iteration; exploration-first; automatic fallback to direct path on failure.
- **🔌 MCP Gateway**: In-app minimal gateway for tool registration/discovery/execution; supports external MCP Server (stdio/streamable-http).
- **🔍 Dual-Engine Code Retrieval**: Combines Zoekt (Regex/Symbol) and Qdrant (Vector Semantic), balancing exact matching and intent understanding.
- **📦 evidence.context_search**: Search within collected evidence context, avoiding redundant code.search/correlation calls.
- **🔗 Full-Link Log Completion**: Automatically pulls context from sources like Aliyun SLS, restoring the complete data flow at the time of failure.
- **📡 Multi-Channel Notification**: Analysis reports are pushed in real-time to WeCom and DingTalk, supporting Markdown format.
- **🛡️ Data Security**: Supports private deployment; code and logs do not leave the intranet (compatible with local LLMs).
- **🪝 Hook System**: AnalysisStart, PreToolUse, PostToolUse, etc., for custom script injection into the analysis lifecycle.

---

## 🆕 v2.0.0 Architecture

v2.0.0 changes the main flow from "direct internal API calls" to **AI-driven**, where the AI autonomously decides tool call order and evidence collection strategy.

### MCP Tools

| Tool | Description |
|------|-------------|
| `index.get_status` | Get repository and index overview |
| `correlation.get_info` | Get correlated logs, trace chain |
| `code.search` | Zoekt code search |
| `code.read` | Read file contents |
| `evidence.context_search` | Search within collected evidence |
| `deps.get_graph` | Dependency topology, call chain |
| `analysis.synthesize` | Generate report from evidence |
| `analysis.run` / `analysis.run_full` | Full analysis (fallback) |

### AI-Driven Flow

```
Plan (plan) → Act (execute tools) → Synthesize (generate report) → Check (self-check + next-round decision)
         ↑                                                                      ↓
         └────────────── If more evidence needed, continue next round ←─────────┘
```

- **Exploration-first**: Fine-grained tools (index/correlation/code.search/evidence.context_search/code.read) take priority over full analysis.run.
- **Failure fallback**: Automatic fallback to direct path on any tool failure or Plan parse failure, ensuring analysis availability.
- **Context discovery**: Pre-fetch index/correlation before Plan; parse trace_id, class name, method name from error_log into prompts.

### AI Gateway & Hooks

- **AI Gateway**: Dynamic switch/add LLM configs (DeepSeek, Doubao, etc.); api_key supports `ENV:VAR_NAME` reference.
- **Hook System**: `~/.rootseek/hooks/` + `config.hooks.dirs`; supports AnalysisStart, AnalysisComplete, PreToolUse, PostToolUse.

See [docs/CHANGELOG_v2.0.0.md](docs/CHANGELOG_v2.0.0.md) for details.

---

## 🛠️ How It Works

```mermaid
graph TB
    subgraph Data Ingestion
        Log["Error Log (SLS)"] --> Ingest["/ingest"]
        Ingest --> Queue["Task Queue"]
    end

    subgraph AI-Driven Analysis
        Queue --> Plan["Plan: AI plans tools"]
        Plan --> Act["Act: Execute MCP tools"]
        Act --> Enrich["Log enrichment"]
        Act --> Zoekt["Zoekt retrieval"]
        Act --> Qdrant["Qdrant retrieval"]
        Enrich --> Context["Build context"]
        Zoekt --> Context
        Qdrant --> Context
        Context --> Synthesize["Synthesize: LLM generates report"]
        Synthesize --> Check["Check: Self-check + next-round decision"]
        Check -->|More evidence needed| Plan
        Check -->|Done| Report["Analysis Report"]
    end

    Report --> Notify["WeCom/DingTalk Notification"]
```

1.  **Ingest**: Receive errors, enqueue analysis tasks.
2.  **Plan**: AI plans which tools to call this round (index/correlation/code.search/evidence.context_search/code.read, etc.).
3.  **Act**: Executor calls MCP tools per plan, collecting evidence.
4.  **Synthesize**: Convert tool results to evidence; LLM generates report for this round.
5.  **Check**: Self-check coverage, consistency, reproducibility; if more evidence needed, AI decides next-round Plan.
6.  **Report**: Generate final report with root cause, evidence, and repair suggestions.

---

## 🏁 Quick Start

### Prerequisites

| Component | Version Requirement | Description |
|-----------|---------------------|-------------|
| **Python** | ≥ 3.11 | Core Service |
| **JDK** | 8 | Admin Dashboard |
| **Docker** | 20+ | Recommended Deployment |

### One-Click Deployment (Docker)

```bash
# 1. Clone repository
git clone https://gitee.com/icey_1/root_seeker.git
cd root_seeker/root_seeker_docker

# 2. Start service (automatically handles config)
bash start.sh
```

After startup, visit:
*   **RootSeeker API**: `http://localhost:8000`
*   **Admin Dashboard**: `http://localhost:8080`

### Manual Installation (macOS/Linux)

```bash
# 1. Copy config
cp config.example.yaml config.yaml

# 2. Install dependencies
bash scripts/install-without-docker.sh

# 3. Start all services
bash scripts/start-all-one-click.sh
```

---

## ⚙️ Configuration

### Enable AI-Driven (default)

```yaml
# config.yaml
ai_driven_enabled: true   # Default true, prefer AI-driven flow
max_analysis_rounds: 20  # Multi-round iteration limit
```

### LLM Configuration

```yaml
llm:
  kind: deepseek
  base_url: "https://api.deepseek.com"
  api_key: "ENV:DEEPSEEK_API_KEY"  # Supports env var reference
  model: "deepseek-chat"
```

### Hooks (optional)

```yaml
hooks:
  enabled: true
  dirs: ["data/hooks"]  # Additional hook directories
```

Place scripts in `~/.rootseek/hooks/` or `config.hooks.dirs`. See [Hook体系说明.md](docs/Hook体系说明.md).

---

## 📖 Deployment Docs

| Document | Description |
|----------|-------------|
| [Config Reference](docs/components/en/00-config-reference.md) | `config.yaml` Explained |
| [Aliyun SLS Integration](docs/components/en/03-aliyun-sls.md) | Log Source Configuration |
| [LLM Configuration](docs/components/en/04-llm.md) | DeepSeek/OpenAI/Doubao Access |
| [Notification Configuration](docs/components/en/07-notifiers.md) | WeCom/DingTalk Bots |
| [v2.0.0 Changelog](docs/CHANGELOG_v2.0.0.md) | MCP Gateway, AI-Driven, Hook System |
| [Hook System](docs/Hook体系说明.md) | Custom script injection into analysis lifecycle |
| [Document Index](docs/文档索引.md) | More docs |

---

## 🔌 API Reference

| Endpoint | Method | Description |
|----------|--------|-------------|
| `/ingest` | POST | Submit error logs for analysis |
| `/ingest/aliyun-sls` | POST | Receive SLS Webhook callbacks |
| `/analysis/{id}` | GET | Query analysis report results |
| `/mcp/tools` | GET | List MCP tools |
| `/mcp/call` | POST | Execute MCP tool |
| `/git-source/repos` | GET | Get repository list |
| `/index/status` | GET | Index status |

See Swagger UI at `http://localhost:8000/docs` for more endpoints.

---

## 💡 Case Study

> **Scenario**: Sudden `NullPointerException` in online transaction service.
>
> **RootSeeker v2.0.0 Performance**:
> 1.  **Plan**: AI plans to call index.get_status, correlation.get_info for context, then code.search to locate DiscountCalculator.
> 2.  **Act**: Executor calls tools per plan; Zoekt locates line 89 of `DiscountCalculator.java`; Qdrant finds the class recently added `@Autowired private VipStrategy vipStrategy;`.
> 3.  **Synthesize**: LLM combines logs and code evidence, concluding the class was instantiated via `new`, causing Spring injection failure.
> 4.  **Check**: Self-check passes; output final report.
> 5.  **Report**: Pushed to WeCom/DingTalk within 30 seconds, suggesting Spring management or constructor injection.

---

## 🤝 Contributing

Pull Requests and Issues are welcome!

1.  Fork this repository
2.  Create Feat_xxx branch
3.  Commit code
4.  Create Pull Request

---

## 📄 License

Apache 2.0 License © 2026 RootSeeker Team

---

**If this project helps you, please give it a Star ⭐️ support!**
