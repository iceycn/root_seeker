# RootSeeker

<p align="center">
    <img src="https://img.shields.io/badge/python-3.11+-blue.svg" alt="Python Version">
    <img src="https://img.shields.io/badge/license-MIT-green.svg" alt="License">
    <img src="https://img.shields.io/badge/docker-ready-blue.svg" alt="Docker">
</p>

[中文](README.md) | [English](README.en.md)

**RootSeeker** is an **AI-driven error analysis and root cause discovery service** designed for internal company networks. It is not just a log parser, but an intelligent SRE with code understanding capabilities.

By integrating **SLS (Logs)**, **Zoekt (Exact Code Search)**, **Qdrant (Semantic Vector Search)**, and **LLM (Large Model Reasoning)**, RootSeeker automatically reconstructs the failure scene, locates problematic code, and generates expert-level repair suggestions.

> **If this project helps you, please give it a Star ⭐️, your support is our motivation!**

---

## 📚 Table of Contents

- [Why Choose RootSeeker?](#-why-choose-rootseeker)
- [Key Features](#-key-features)
- [How It Works](#-how-it-works)
- [Quick Start](#-quick-start)
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
*   **Multi-turn Detective Reasoning**: Thinks like a human expert, gradually approaching the root cause through multi-turn questioning and secondary retrieval.

---

## ✨ Key Features

- **🔍 Dual-Engine Code Retrieval**: Combines Zoekt (Regex/Symbol) and Qdrant (Vector Semantic), balancing exact matching and intent understanding.
- **🤖 Intelligent Root Cause Analysis**: Based on RAG (Retrieval-Augmented Generation) technology, utilizing large models like DeepSeek/ChatGPT for deep reasoning.
- **🔗 Full-Link Log Completion**: Automatically pulls context from sources like Aliyun SLS, restoring the complete data flow at the time of failure.
- **📡 Multi-Channel Notification**: Analysis reports are pushed in real-time to WeCom and DingTalk, supporting Markdown format.
- **🛡️ Data Security**: Supports private deployment; code and logs do not leave the intranet (compatible with local LLMs).
- **⚡️ Efficient Token Management**: Built-in AST slicing and precise Token counting maximize the use of the LLM context window.

---

## 🛠️ How It Works

```mermaid
graph LR
    Log[Error Log (SLS)] --> Ingest[Data Ingestion]
    Ingest --> Enrich[Log Enrichment (TraceID)]
    Enrich --> Retrieval[Dual Retrieval]
    Retrieval --> Zoekt[Zoekt (Exact)]
    Retrieval --> Qdrant[Qdrant (Semantic)]
    Zoekt & Qdrant --> Context[Build Context]
    Context --> LLM[LLM Reasoning]
    LLM --> Report[Generate Report]
    Report --> Notify[WeCom/DingTalk Notification]
```

1.  **Ingest & Enrich**: Receive errors, automatically backtrack TraceID to pull context.
2.  **Retrieval**: Extract keywords, parallel retrieval from code repositories (Zoekt locates physical position, Qdrant understands logical associations).
3.  **Analysis**: LLM performs multi-turn reasoning (Chain of Thought), requesting supplementary evidence if necessary.
4.  **Report**: Generate a final report containing root cause, evidence, and repair suggestions.

---

## 🏁 Quick Start

### Prerequisites

| Component | Version Requirement | Description |
|-----------|---------------------|-------------|
| **Python** | ≥ 3.11 | Core Service |
| **JDK** | 8 | Admin Dashboard |
| **Docker** | 20+ | Recommended Deployment |

### One-Click Deployment (Docker)

The easiest way to experience it is using Docker Compose:

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

## 📖 Deployment Docs

We provide detailed component documentation to help you build a production-grade environment from scratch:

*   [**Config Reference**](docs/components/en/00-config-reference.md): `config.yaml` Explained
*   [**Aliyun SLS Integration**](docs/components/en/03-aliyun-sls.md): Log Source Configuration
*   [**LLM Configuration**](docs/components/en/04-llm.md): DeepSeek/OpenAI/Doubao Access
*   [**Notification Configuration**](docs/components/en/07-notifiers.md): WeCom/DingTalk Bots
*   [**More Docs...**](docs/文档索引.md)

---

## 🔌 API Reference

| Endpoint | Method | Description |
|----------|--------|-------------|
| `/ingest` | POST | Submit error logs for analysis |
| `/ingest/aliyun-sls` | POST | Receive SLS Webhook callbacks |
| `/git-source/repos` | GET | Get repository list |
| `/analysis/{id}` | GET | Query analysis report results |

See `main.py` or the Swagger UI (`/docs`) after startup for more endpoints.

---

## 💡 Case Study

> **Scenario**: Sudden `NullPointerException` in online transaction service.
>
> **RootSeeker's Performance**:
> 1.  **Capture**: Received error log, automatically pulled API inputs under the same TraceID.
> 2.  **Retrieval**: Located line 89 of `DiscountCalculator.java` via Zoekt.
> 3.  **Discovery**: Discovered via Qdrant that the class recently added `@Autowired private VipStrategy vipStrategy;`.
> 4.  **Reasoning**: LLM combined with logs pointed out that the class was instantiated manually via `new`, causing Spring injection failure, resulting in the field being null.
> 5.  **Report**: Pushed report within 30 seconds, suggesting changing to Spring management or constructor injection.

---

## 🤝 Contributing

Pull Requests and Issues are welcome!

1.  Fork this repository
2.  Create Feat_xxx branch
3.  Commit code
4.  Create Pull Request

---

## 📄 License

MIT License © 2024 RootSeeker Team

---

**If this project helps you, please give it a Star ⭐️ support!**
