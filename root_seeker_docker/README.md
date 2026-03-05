# RootSeeker Docker 全栈部署（开箱即用）

本目录用于 RootSeeker 的 Docker 部署，**一键启动全部组件**：MySQL、Qdrant、Zoekt、RootSeeker、RootSeeker Admin。

## 前置要求

- 已安装 Docker 与 Docker Compose
- （可选）Python 3，用于一键脚本自动合并配置
- **国内用户**：若无法连接 Docker Hub，请先配置镜像加速，见 [docker-mirror-config.md](docker-mirror-config.md)

## 一键启动（开箱即用）

```bash
# 在项目根目录执行
bash root_seeker_docker/start.sh
```

Windows PowerShell：

```powershell
.\root_seeker_docker\start.ps1
```

**脚本自动完成**：
- 创建 `data/` 目录
- 启动全部容器
- **MySQL 首次启动** → 自动执行 `mysql-init/sql/` 下全部 SQL，初始化若依表、Git 仓库表、**完整 Demo 配置**（app_config：LLM、Embedding、Qdrant、Zoekt、阿里云 SLS 等）、预置 Demo 仓库（psf/requests），并设置 `root.seeker.baseUrl` 为 `http://root-seeker:8000`

## 手动启动

```bash
cd root_seeker_docker
docker compose up -d --build

# 查看日志
docker compose logs -f root-seeker
docker compose logs -f root-seeker-admin
```

## 停止

```bash
cd root_seeker_docker
docker compose down
```

## 服务地址

| 服务 | 地址 | 说明 |
|------|------|------|
| RootSeeker | http://localhost:8000 | 分析服务 API |
| RootSeeker Admin | http://localhost:8088 | 管理端（默认 admin/admin123，8088 避免与本地 Apache 冲突） |
| Qdrant | http://localhost:6333 | 向量库 |
| Zoekt | http://localhost:6070 | 词法检索 |
| MySQL | localhost:3307 | 数据库 root_seeker（宿主机 3307 映射容器 3306） |

## 配置说明

- **Docker 默认使用 MySQL 模式**：`config_source=database`，配置存储在 `app_config` 表，初始化时已写入完整 Demo（LLM、Embedding、Qdrant、Zoekt、阿里云 SLS、企微、钉钉、Git 仓库发现），可在 Admin「Git 源码管理 → AI应用配置」中查看/编辑
- **Demo 仓库**：预置 `psf/requests`，可在 Admin「Git 源码管理」中同步并建索引
- RootSeeker 容器默认挂载 [config.docker.yaml](file:///Users/beisen/PycharmProjects/root_seek/root_seeker_docker/config.docker.yaml) 到 `/app/config.yaml`
- **Zoekt 索引**：初始为空。同步仓库后，在 Admin「Git 源码管理」中点击对应仓库的「Zoekt 索引」即可（RootSeeker 容器已内置 zoekt-index，索引写入与 zoekt-webserver 共享的目录）

## SQL 更新同步

当 `ruoyi-rootseeker-admin/sql` 有更新时，执行 `bash root_seeker_docker/sync-sql.sh` 或 `.\root_seeker_docker\sync-sql.ps1` 同步到 `mysql-init/sql`。

## 组件说明

- **MySQL**：若依系统表 + git_source + app_config，首次启动自动初始化（表结构已内置在 mysql-init/sql/）
- **Qdrant**：向量检索
- **Zoekt**：词法检索（需先同步仓库并建索引）
- **RootSeeker**：Python 分析服务
- **RootSeeker Admin**：若依 Java 管理端，连接 MySQL 与 RootSeeker
