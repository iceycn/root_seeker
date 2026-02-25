# RootSeeker

面向公司内网的错误分析与根因发现服务：SLS(Webhook+主动补全) → Zoekt(词法检索) → Qdrant(向量检索) → 云端 LLM(DeepSeek/豆包) → 企业微信/钉钉推送。

中文（默认） | [English](README.en.md)

## 快速开始

```bash
# 1. 复制配置
cp config.example.yaml config.yaml

# 2. 修改 config.yaml（至少填 repos、aliyun_sls、llm 等）

# 3. 一键安装依赖（Python + Go + Zoekt + Qdrant）
bash scripts/install-without-docker.sh

# 4. 按顺序启动（见下方「启动顺序」）
```

## 启动顺序

| 步骤 | 组件 | 命令 |
|------|------|------|
| 1 | Qdrant | `./tools/qdrant --config-path config/qdrant_config.yaml` |
| 2 | Zoekt | 先执行 `bash scripts/index-zoekt-all.sh` 建索引，再 `zoekt-webserver -index data/zoekt/index -listen :6070` |
| 3 | 应用 | `python3 -m uvicorn main:app --host 0.0.0.0 --port 8000` |

验证：`bash scripts/check-services.sh` 或 `curl http://127.0.0.1:8000/healthz`

## 组件配置文档（傻瓜式）

每个组件单独一页，配置、初始化、常见问题一应俱全：

| 组件 | 文档 | 说明 |
|------|------|------|
| **配置参考** | [docs/components/00-config-reference.md](docs/components/00-config-reference.md) | 所有配置项完整列表 |
| **Zoekt** | [docs/components/01-zoekt.md](docs/components/01-zoekt.md) | 词法检索：配置、安装、为仓库建索引 |
| **Qdrant** | [docs/components/02-qdrant.md](docs/components/02-qdrant.md) | 向量库：配置、为代码仓库建向量索引 |
| **阿里云 SLS** | [docs/components/03-aliyun-sls.md](docs/components/03-aliyun-sls.md) | 日志补全：AK/SK、project、logstore、SQL 模板 |
| **LLM** | [docs/components/04-llm.md](docs/components/04-llm.md) | 大模型：DeepSeek/豆包、超时、重试 |
| **Embedding** | [docs/components/05-embedding.md](docs/components/05-embedding.md) | 向量模型：代码向量化配置 |
| **仓库配置** | [docs/components/06-repos.md](docs/components/06-repos.md) | 代码仓库：repos、同步、索引流程 |
| **通知** | [docs/components/07-notifiers.md](docs/components/07-notifiers.md) | 企业微信/钉钉 Webhook |
| **数据存储** | [docs/components/08-data-storage.md](docs/components/08-data-storage.md) | 无数据库，文件存储结构、目录说明 |

## 常用接口

| 接口 | 说明 |
|------|------|
| `POST /ingest` | 提交错误日志（通用 JSON） |
| `POST /ingest/aliyun-sls` | 提交错误日志（SLS 原始格式） |
| `GET /analysis/{analysis_id}` | 查询分析结果 |
| `POST /repos/sync` | 同步/拉取仓库（git clone/pull） |
| `POST /index/repo/{service_name}` | 为指定仓库建向量索引 |
| `POST /graph/rebuild` | 重建服务依赖图 |

## 鉴权

若在 `config.yaml` 中配置了 `api_keys`，请求需携带：`X-API-Key: <your_key>`

## 更多文档

- [部署总览](docs/deploy/00-overview.md)
- [文档索引](docs/DOCUMENTATION_INDEX.md)
