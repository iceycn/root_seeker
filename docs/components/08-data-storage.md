# 数据存储说明

RootSeeker **不使用传统数据库**，所有数据以 JSON 文件形式存储在本地目录。

## 零、存储模式（先看这个）

RootSeeker 的“分析结果与状态”默认落地到本地文件（`data_dir`），但项目整体支持多种存储/配置模式：

| 模式 | 是否需要 MySQL | 涉及组件 | 说明 |
|------|----------------|----------|------|
| A. 纯文件模式（默认） | 否 | RootSeeker | 分析结果、任务状态、依赖图等落本地文件 |
| B. Git 仓库发现 MySQL 模式（可选） | 是 | RootSeeker | 当 `git_source.storage.type=mysql` 时，RootSeeker 会读写 MySQL 保存仓库与凭证 |
| C. 管理端 + 配置库模式（常见于 Docker） | 是 | RootSeeker Admin | Admin 运行依赖 MySQL；Docker 默认还会启用 `config_source=database` 将配置存入 `app_config` |

## 一、目录结构

```
data/                          # 由 config.yaml 中 data_dir 指定，默认 data
├── analyses/                  # 分析报告
│   ├── {analysis_id}.json
│   └── ...
├── status/                    # 任务状态（pending/running/completed/failed）
│   ├── {analysis_id}.json
│   └── ...
├── service_graph.json         # 服务依赖图（由 POST /graph/rebuild 生成）
├── qdrant_storage/            # Qdrant 向量库数据（若用项目内配置）
└── zoekt/
    └── index/                 # Zoekt 索引目录

audit_dir/                     # 审计日志（若配置 audit_dir）
└── ...
```

## 二、无需数据库初始化

- **纯文件模式**：不需要 MySQL、PostgreSQL 等，无需执行建表脚本。
- **自动创建**：`AnalysisStore`、`StatusStore` 在首次写入时会自动创建 `analyses/`、`status/` 目录（`mkdir -p`）。
- **Qdrant**：向量库由 Qdrant 自身管理，应用首次执行 `POST /index/repo/{service_name}` 时会自动创建 collection，无需手动初始化。

若启用模式 B/C：

- RootSeeker Admin 的 MySQL 初始化见 `ruoyi-rootseeker-admin/README_ROOTSEEKER.md`
- Docker 一键（含 MySQL/初始化 SQL）见 `root_seeker_docker/README.md`

## 三、各存储说明

| 路径 | 说明 |
|------|------|
| data/analyses/ | 分析报告，每份一个 JSON 文件，文件名即 analysis_id |
| data/status/ | 任务状态，用于 `GET /analysis/{id}` 返回 running/failed 等 |
| data/service_graph.json | 服务依赖图，由 `POST /graph/rebuild` 生成 |
| data/qdrant_storage/ | Qdrant 数据目录，见 config/qdrant_config.yaml |
| data/zoekt/index/ | Zoekt 索引，由 scripts/index-zoekt-all.sh 生成 |

## 四、备份与迁移

- 备份 `data/` 目录即可保留分析结果与状态。
- Qdrant 数据在 `data/qdrant_storage/`，需单独备份。
- Zoekt 索引在 `data/zoekt/index/`，迁移时需一并拷贝。

## 五、依赖支持

- **Python 3.11+**
- **文件系统**：需对 `data_dir` 有读写权限
- **Git**：仓库同步用
- **无额外数据库驱动**：不依赖 pymysql、psycopg2 等

[English](en/08-data-storage.md)
