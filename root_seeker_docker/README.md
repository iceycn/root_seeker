# RootSeeker Docker 化

本目录用于 RootSeeker 的 Docker 部署，包含 Qdrant + RootSeeker 核心服务。

## 前置要求

- 已安装 Docker 与 Docker Compose
- 项目根目录已有 `config.yaml`（可复制 `config.example.yaml` 并修改）

## 配置

Docker 内 RootSeeker 需通过服务名访问 Qdrant。在 `config.yaml` 中设置：

```yaml
qdrant:
  url: "http://qdrant:6333"   # 容器内使用服务名，非 localhost
  api_key: null
  collection: "code_chunks"
```

或创建 `config.docker.yaml` 覆盖上述配置，并在 docker-compose 中挂载。

## 启动

```bash
# 在项目根目录执行
cd root_seeker_docker
docker compose up -d

# 查看日志
docker compose logs -f root-seeker
```

## 停止

```bash
cd root_seeker_docker
docker compose down
```

## 服务地址

| 服务 | 地址 |
|------|------|
| RootSeeker | http://localhost:8000 |
| Qdrant | http://localhost:6333 |

## 说明

- **Zoekt**：未包含，词法检索需本地索引，可按需单独部署
- **RootSeeker Admin**：未包含，Java 若依项目需单独部署或使用宿主机一键脚本
