# RootSeeker

<p align="center">
    <img src="https://img.shields.io/badge/python-3.11+-blue.svg" alt="Python Version">
    <img src="https://img.shields.io/badge/license-Apache-green.svg" alt="License">
    <img src="https://img.shields.io/badge/docker-ready-blue.svg" alt="Docker">
</p>

<p align="center">
  <strong><a href="README.md">中文</a></strong> | <strong><a href="README.en.md">English</a></strong>
</p>

**RootSeeker** 是一个面向公司内网的 **AI 驱动错误分析与根因发现服务**。它不仅仅是一个日志解析器，更是一个拥有代码理解能力的智能 SRE。

通过集成 **SLS (日志)**、**Zoekt (精确代码检索)**、**Qdrant (语义向量检索)** 和 **LLM (大模型推理)**，RootSeeker 能够自动还原故障现场，定位问题代码，并生成专家级的修复建议。

> **如果觉得这个项目对你有帮助，请帮忙点个 Star ⭐️，你的支持是我们更新的动力！**

---

## 📚 目录

- [为什么选择 RootSeeker？](#-为什么选择-rootseeker)
- [核心特性](#-核心特性)
- [工作原理](#-工作原理)
- [快速开始](#-快速开始)
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
*   **多轮侦探推理**：像人类专家一样思考，通过多轮追问和二次检索，逐步逼近根因。

---

## ✨ 核心特性

- **🔍 双引擎代码检索**：结合 Zoekt（正则/符号）和 Qdrant（向量语义），兼顾精确匹配与意图理解。
- **🤖 智能根因分析**：基于 RAG（检索增强生成）技术，利用 DeepSeek/ChatGPT 等大模型进行深度推理。
- **🔗 全链路日志补全**：自动从阿里云 SLS 等源拉取上下文，还原故障发生时的完整数据流。
- **📡 多渠道触达**：分析报告实时推送至企业微信、钉钉，支持 Markdown 格式。
- **🛡️ 数据安全**：支持私有化部署，代码和日志不出内网（可对接本地 LLM）。
- **⚡️ 高效 Token 管理**：内置 AST 切片与精准 Token 计数，最大化利用 LLM 上下文窗口。

---

## 🛠️ 工作原理

```mermaid
graph LR
    Log[错误日志 (SLS)] --> Ingest[数据摄入]
    Ingest --> Enrich[日志补全 (TraceID)]
    Enrich --> Retrieval[双路检索]
    Retrieval --> Zoekt[Zoekt (精确)]
    Retrieval --> Qdrant[Qdrant (语义)]
    Zoekt & Qdrant --> Context[构建上下文]
    Context --> LLM[大模型推理]
    LLM --> Report[生成报告]
    Report --> Notify[企微/钉钉通知]
```

1.  **Ingest & Enrich**：接收报错，自动回溯 TraceID 拉取前后文。
2.  **Retrieval**：提取关键词，并行检索代码库（Zoekt 定位物理位置，Qdrant 理解逻辑关联）。
3.  **Analysis**：LLM 进行多轮推理（Chain of Thought），必要时请求补充证据。
4.  **Report**：生成包含根因、证据和修复建议的最终报告。

---

## 🏁 快速开始

### 环境要求

| 组件 | 版本要求 | 说明 |
|------|----------|------|
| **Python** | ≥ 3.11 | 核心服务 |
| **JDK** | 8 | Admin 管理后台 |
| **Docker** | 20+ | 推荐部署方式 |

### 一键部署 (Docker)

最简单的体验方式是使用 Docker Compose：

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

## 📖 部署文档

我们提供了详尽的组件文档，帮助你从零开始搭建生产级环境：

*   [**配置参考**](docs/components/00-config-reference.md): `config.yaml` 全解
*   [**阿里云 SLS 集成**](docs/components/03-aliyun-sls.md): 日志源配置
*   [**LLM 配置**](docs/components/04-llm.md): DeepSeek/OpenAI/豆包接入
*   [**通知配置**](docs/components/07-notifiers.md): 企微/钉钉机器人
*   [**更多文档...**](docs/DOCUMENTATION_INDEX.md)

---

## 🔌 API 参考

| 接口 | 方法 | 说明 |
|------|------|------|
| `/ingest` | POST | 提交错误日志进行分析 |
| `/ingest/aliyun-sls` | POST | 接收 SLS Webhook 回调 |
| `/git-source/repos` | GET | 获取仓库列表 |
| `/analysis/{id}` | GET | 查询分析报告结果 |

更多接口请查看代码中的 `main.py` 或启动后的 Swagger UI (`/docs`)。

---

## 💡 案例分析

> **场景**：线上交易服务突发 `NullPointerException`。
>
> **RootSeeker 的表现**：
> 1.  **捕获**：接收到报错日志，自动拉取同一 TraceID 下的 API 入参。
> 2.  **检索**：通过 Zoekt 定位到 `DiscountCalculator.java` 第 89 行。
> 3.  **发现**：通过 Qdrant 发现该类最近新增了 `@Autowired private VipStrategy vipStrategy;`。
> 4.  **推理**：LLM 结合日志指出，该类是由 `new` 关键字手动实例化的，导致 Spring 注入失败，字段为 null。
> 5.  **报告**：30 秒内推送报告，建议改为 Spring 托管或构造函数注入。

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
