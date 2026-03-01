# RootSeeker

面向公司内网的错误分析与根因发现服务：SLS(Webhook+主动补全) → Zoekt(词法检索) → Qdrant(向量检索) → 云端 LLM(DeepSeek/豆包) → 企业微信/钉钉推送。

项目地址：<https://gitee.com/icey_1/root_seeker>

中文（默认） | [English](README.en.md)

## 快速开始

### 环境要求（必须安装）

| 组件 | 版本要求 | 说明 |
|------|----------|------|
| **Python** | ≥ 3.11 | RootSeeker 核心，`python3 --version` 检查 |
| **JDK** | 8 | RootSeeker Admin（若依），`java -version` 检查 |
| **Maven** | 3.x | RootSeeker Admin 构建，`mvn -v` 检查 |
| **Go** | 最新 | Zoekt 词法检索，`go version` 检查 |
| **Qdrant** | v1.16.3 | 向量库，由 `install-without-docker.sh` 自动下载 |
| **Zoekt** | latest | 词法检索，由 `install-without-docker.sh` 自动安装 |

**可选**：MySQL（当 `git_source.storage.type=mysql` 或 `config_source=database` 时需配置）

- macOS 安装示例：`brew install python@3.11 openjdk@8 maven go`
- Windows：需手动安装 Python、JDK、Maven、Go，或使用 Chocolatey：`choco install python openjdk8 maven golang`
- **Qdrant / Zoekt 自行安装**：见 [依赖组件安装指南](docs/INSTALL_DEPENDENCIES.md)

### 安装与启动

**macOS / Linux：**

```bash
# 1. 复制配置
cp config.example.yaml config.yaml

# 2. 修改 config.yaml（至少填 repos、aliyun_sls、llm 等）

# 3. 一键安装依赖（Python 包 + Go + Zoekt + Qdrant）
bash scripts/install-without-docker.sh

# 4. 一键启动
bash scripts/start-all-one-click.sh
```

**Windows：**

```powershell
# 1. 复制配置
Copy-Item config.example.yaml config.yaml

# 2. 修改 config.yaml

# 3. 一键安装
.\scripts\install-without-docker.ps1

# 4. 一键启动
.\scripts\start-all-one-click.bat
```

## 启动顺序

### 一键启动（推荐）

| 平台 | 启动 | 停止 |
|------|------|------|
| **macOS / Linux** | `bash scripts/start-all-one-click.sh` | `bash scripts/stop-all-one-click.sh` |
| **Windows** | `scripts\start-all-one-click.bat` | `scripts\stop-all-one-click.bat` |

启动后访问：RootSeeker `http://localhost:8000` | RootSeeker Admin `http://localhost:8080` | 日志目录 `logs/`

### Docker 部署（可选）

若已安装 Docker，可使用 `root_seeker_docker` 一键启动 Qdrant + RootSeeker：

```bash
# 一键启动（自动处理 config.yaml 与 qdrant 地址）
bash root_seeker_docker/start.sh
```

Windows PowerShell：`.\root_seeker_docker\start.ps1`

或手动：`cd root_seeker_docker && docker compose up -d`

详见 [root_seeker_docker/README.md](root_seeker_docker/README.md)

### 手动启动

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
| **批量聚类** | [docs/components/09-batch-cluster.md](docs/components/09-batch-cluster.md) | 批量日志聚类、相似问题分组与抽样分析 |
| **Git 仓库发现** | [docs/components/10-git-source.md](docs/components/10-git-source.md) | 根据域名+账号获取仓库列表，分支选择，文件/MySQL 存储 |

## 常用接口

| 接口 | 说明 |
|------|------|
| `POST /ingest` | 提交错误日志（通用 JSON） |
| `POST /ingest/aliyun-sls` | 提交错误日志（SLS 原始格式） |
| `POST /ingest/batch-cluster` | 批量日志聚类：传入日志列表，算法分组相似问题并抽样分析（少用 AI） |
| `PUT /git-source/config` | 保存平台凭证（Gitee/GitHub/Codeup 等），一次配置 |
| `GET /git-source/repos` | 获取仓库列表（统一接口） |
| `GET /git-source/repos/{id}` | 获取仓库详情（含分支） |
| `PUT /git-source/repos/{id}` | 配置仓库到分析工具（启用、选分支） |
| `POST /git-source/sync` | 同步仓库到本地，供分析使用 |
| `GET /analysis/{analysis_id}` | 查询分析结果 |
| `POST /repos/sync` | 同步/拉取仓库（git clone/pull） |
| `POST /index/repo/{service_name}` | 为指定仓库建向量索引 |
| `POST /index/repo/{service_name}/reset` | 单仓库全量重置（清除向量并重索引） |
| `POST /index/reset-all` | 强制清除全部向量，`?reindex=true` 可重索引（按仓库排队） |
| `POST /repos/full-reload` | 全量重载：同步 + 清除向量 + 重索引（按仓库排队） |
| `POST /graph/rebuild` | 重建服务依赖图 |

## 鉴权

若在 `config.yaml` 中配置了 `api_keys`，请求需携带：`X-API-Key: <your_key>`

## 更多文档

- [依赖组件安装指南](docs/INSTALL_DEPENDENCIES.md) - Qdrant、Zoekt 等自行安装
- [部署总览](docs/deploy/00-overview.md)
- [Docker 部署](root_seeker_docker/README.md)
- [文档索引](docs/DOCUMENTATION_INDEX.md)
