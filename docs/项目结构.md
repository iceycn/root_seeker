# 项目结构说明与检查结论

## 1. 项目结构总览

```
RootSeeker/
├── main.py                 # 入口，挂载 FastAPI app
├── config.example.yaml     # 配置示例
├── pyproject.toml         # 依赖与项目元数据
├── README.md              # 使用说明
├── .trae/documents/       # 方案设计文档（trae 生成）
├── root_seeker/           # 主包
│   ├── app.py             # FastAPI 应用组装与路由
│   ├── config.py          # 配置 Schema（Pydantic）
│   ├── domain.py          # 领域模型（IngestEvent、AnalysisReport 等）
│   ├── sql_templates.py   # SQL 模板注册表
│   ├── security.py       # API Key 鉴权
│   ├── indexing/          # 代码切分
│   │   └── chunker.py     # Tree-sitter 切分（Python/Java）
│   ├── providers/         # 外部依赖适配
│   │   ├── sls.py         # 阿里云 SLS 日志查询
│   │   ├── zoekt.py       # Zoekt 词法检索客户端
│   │   ├── qdrant.py      # Qdrant 向量存储
│   │   ├── embedding.py  # FastEmbed / Hash 向量化
│   │   ├── llm.py         # OpenAI 兼容 LLM（DeepSeek/豆包）
│   │   ├── llm_wrapped.py # 限流 + 熔断 + 审计
│   │   └── notifiers.py   # 企业微信 / 钉钉
│   ├── services/          # 业务服务
│   │   ├── router.py      # 服务名 → 仓库路由（显式 + 启发式）
│   │   ├── repo_mirror.py # Git 拉取/同步
│   │   ├── enricher.py    # 日志补全（query_key → SQL 模板 → SLS）
│   │   ├── analyzer.py   # 分析流水线（路由→补全→Zoekt/Qdrant→证据→LLM→通知）
│   │   ├── evidence.py   # 证据包构建（Zoekt 命中 + 向量命中 + 配置片段）
│   │   ├── vector_indexer.py  # 仓库向量索引
│   │   ├── vector_retriever.py # 向量检索
│   │   └── service_graph.py   # 上下游依赖图构建与查询
│   ├── storage/           # 持久化
│   │   ├── analysis_store.py  # 分析结果存储
│   │   ├── status_store.py   # 任务状态
│   │   └── audit_log.py      # 审计日志
│   └── runtime/           # 运行时
│       ├── job_queue.py   # 异步分析任务队列
│       └── circuit_breaker.py # 熔断（LLM 等）
└── tests/                  # 单元测试
```

## 2. 结构检查结论

| 维度 | 结论 | 说明 |
|------|------|------|
| **分层** | ✅ 合理 | 入口 → 应用组装 → 领域/服务/提供方/存储 分层清晰 |
| **高内聚** | ✅ 良好 | 每模块职责单一：router 只做路由，enricher 只做补全，analyzer 编排流水线 |
| **低耦合** | ✅ 良好 | 通过 Protocol/接口（CloudLogProvider、LLMProvider、Notifier）与配置注入解耦 |
| **可扩展** | ✅ 已预留 | 新日志源：实现 CloudLogProvider；新通知：实现 Notifier；新 LLM：OpenAI 兼容即可 |
| **设计模式** | ✅ 已用 | Adapter（SLS/Zoekt/Qdrant/Notifier）、Registry（SqlTemplate）、策略式路由、队列+Worker |
| **配置** | ✅ 集中 | 单 YAML + Pydantic 校验，环境变量可指定 `ROOT_SEEKER_CONFIG_PATH` |
| **文档位置** | ⚠️ 分散 | 方案在 `.trae/documents/`，使用说明在 README，缺少「文档索引」与「部署手册」 |

**总体结论**：项目结构 OK，符合公司级可扩展、高内聚低耦合的要求；主要缺口在「文档整合」和「各组件傻瓜式部署说明」。

## 3. 与方案文档的对应关系

- **数据流**：Webhook → 归一化 → 路由 → SLS 补全 → Zoekt + Qdrant 检索 → 证据包 → LLM → 通知，与 `.trae/documents/公司级AI错误分析与代码检索工具方案.md` 中描述一致。
- **模块化**：Ingress（Webhook）、Log Enrichment（SqlTemplateRegistry + AliyunSLSProvider）、Repo（RepoCatalog + RepoMirror）、Indexing（TreeSitterChunker + Zoekt + Qdrant）、Analysis（AnalyzerService + LLM）、Egress（WeCom/DingTalk）均已实现。
- **安全与审计**：API Key 鉴权、审计日志（AuditLogger）、证据包上限（max_evidence_*）已具备；脱敏/白名单可后续在证据组装或 LLM 前链路补充。
