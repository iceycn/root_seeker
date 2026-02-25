# 部署总览

本文档说明 RootSeeker 及其依赖的部署顺序与关系，便于内网从零搭起一整套环境。

## 1. 组件依赖关系

```
                    ┌─────────────────┐
                    │  阿里云 SLS      │  （日志补全，可选）
                    └────────┬────────┘
                             │
  ┌──────────────┐    ┌──────▼──────┐    ┌──────────────┐
  │  Zoekt       │    │ RootSeeker│    │  Qdrant      │
  │  (词法检索)   │◄───┤   (本应用)   ├───►│  (向量库)    │
  └──────┬───────┘    └──────┬──────┘    └──────┬───────┘
         │                   │                   │
         │                   │                   │
         ▼                   ▼                   ▼
  ┌──────────────┐    ┌──────────────┐    ┌──────────────┐
  │ 本地 Git     │    │ 企业微信/钉钉 │    │ 本地磁盘      │
  │ 仓库目录      │    │ (通知)       │    │ (持久化)      │
  └──────────────┘    └──────────────┘    └──────────────┘
```

- **RootSeeker**：核心服务，依赖 Zoekt（可选）、Qdrant（可选）、阿里云 SLS（可选）、企业微信/钉钉（可选）。所有外部依赖均可通过配置关闭。
- **Zoekt**：用于代码词法/符号检索，需先部署并索引本地仓库，本应用通过 HTTP 调用其 API。
- **Qdrant**：用于代码向量检索，需先部署；本应用在「向量索引」与「分析检索」时访问。
- **阿里云 SLS**：用于根据 `query_key` 拉取更多日志；需配置 AK/SK、project、logstore 及 SQL 模板。
- **企业微信/钉钉**：分析完成后推送 Markdown 到群；配置 webhook 即可。

## 2. 推荐部署顺序（内网自托管）

| 步骤 | 组件 | 文档 | 说明 |
|------|------|------|------|
| 1 | 准备目录与 Git 仓库 | 见下 | 为每个服务准备 `local_dir`，并确保可 clone/pull |
| 2 | Zoekt | [01-zoekt.md](01-zoekt.md) | 部署 Zoekt 并对仓库建索引 |
| 3 | Qdrant | [02-qdrant.md](02-qdrant.md) | 部署 Qdrant，无需预先建 collection（应用会按需创建） |
| 4 | RootSeeker | [03-RootSeeker.md](03-RootSeeker.md) | 填写 config.yaml，启动应用 |
| 5 | 阿里云 SLS（可选） | [04-aliyun-sls.md](04-aliyun-sls.md) | 配置 AK/SK、project、logstore、sql_templates |
| 6 | 企业微信/钉钉（可选） | [05-notifiers.md](05-notifiers.md) | 配置 webhook_url |

## 3. 最小可运行配置（不接任何云）

- 不配置 `zoekt`、`qdrant`、`llm`、`wecom`/`dingtalk`、`aliyun_sls` 时，应用会启动，但：
  - 分析时不会做 Zoekt/向量检索，证据包可能为空；
  - 不会调 LLM，报告为固定文案「未配置云端LLM」；
  - 不会推送通知。
- 若要「仅做路由 + 存储 + 查询」，可保留 `repos` 与 `data_dir`，其余均可省略；此时需在 config 中提供至少一个占位项以满足 Pydantic（例如保留 `aliyun_sls` 占位，或后续将 aliyun_sls 改为可选）。

**说明**：当前 `config.py` 中 `aliyun_sls` 为必填。若希望「完全脱云」运行，需要将 `AppConfig.aliyun_sls` 改为 `Optional` 并在 `app.py` 中在无 SLS 时跳过 enricher 或使用空实现。此处仅作说明，不改动代码。

## 4. 目标时延（3 分钟）

- 在线路径：Webhook 接收 → 入队 → 异步分析（路由 → SLS 补全 → Zoekt + Qdrant 检索 → 证据包 → LLM → 存盘 → 通知）。
- 索引与依赖图构建均在后台或手动触发（如 `POST /index/repo/{service_name}`、`POST /graph/rebuild`），不占 3 分钟。
- 若需保障 3 分钟 SLA，建议：为分析任务设超时（如 160s），并确保 Zoekt/Qdrant/LLM 在内网或低延迟可达。

## 5. 文档索引

- 各组件傻瓜式步骤见：[01-zoekt](01-zoekt.md)、[02-qdrant](02-qdrant.md)、[03-RootSeeker](03-RootSeeker.md)、[04-aliyun-sls](04-aliyun-sls.md)、[05-notifiers](05-notifiers.md)。
- 项目结构与优化建议见上级目录 [PROJECT_STRUCTURE.md](../PROJECT_STRUCTURE.md)、[OPTIMIZATION_CHECKLIST.md](../OPTIMIZATION_CHECKLIST.md)。
- 设计与需求总览（含项目检查结论）见 [DESIGN_AND_REQUIREMENTS.md](../DESIGN_AND_REQUIREMENTS.md)；文档整合索引见 [DOCUMENTATION_INDEX.md](../DOCUMENTATION_INDEX.md)。
