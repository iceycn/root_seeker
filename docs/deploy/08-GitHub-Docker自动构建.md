# GitHub 自动构建 Docker 镜像

## 一、概述

项目已配置 GitHub Actions 工作流，在推送代码时自动构建 RootSeeker Docker 镜像并**同时推送至 ghcr.io 与 Docker Hub**。

- **ghcr.io**：无需配置，使用 `GITHUB_TOKEN` 自动推送
- **Docker Hub**：需配置 Secret（见下方）

## 二、前置配置（Docker Hub 必填）

在 GitHub 仓库 **Settings → Secrets and variables → Actions** 中新增：

| Secret 名称 | 说明 |
|-------------|------|
| `DOCKERHUB_USERNAME` | Docker Hub 用户名 |
| `DOCKERHUB_TOKEN` | Docker Hub Access Token（在 [hub.docker.com](https://hub.docker.com) → Account Settings → Security → New Access Token 创建） |

## 三、触发条件

| 事件 | 触发分支/标签 | 是否推送镜像 |
|------|---------------|--------------|
| `push` | `main`、`master`、`feature/3.0.0` | ✅ 是 |
| `push` | 标签 `v*`（如 v3.0.0） | ✅ 是 |
| `pull_request` | 目标为 main/master | ❌ 否（仅构建验证） |

## 四、镜像地址与标签

| 仓库 | 地址示例 |
|------|----------|
| ghcr.io | `ghcr.io/iceycn/root-seeker` |
| Docker Hub | `<DOCKERHUB_USERNAME>/root-seeker` |

| 触发方式 | 示例标签 |
|----------|----------|
| 推送到 main | `latest` |
| 推送到 feature/3.0.0 | `feature-3.0.0` |
| 推送标签 v3.0.0 | `v3.0.0`、`3.0.0` |
| 任意提交 | `sha-<short_sha>` |

## 五、使用方式

```bash
# 从 ghcr.io 拉取（无需登录，若为公开镜像）
docker pull ghcr.io/iceycn/root-seeker:latest

# 从 Docker Hub 拉取
docker pull <你的DockerHub用户名>/root-seeker:latest

# 拉取指定版本
docker pull ghcr.io/iceycn/root-seeker:v3.0.0
```

## 六、配置说明

### 6.1 增加触发分支

编辑 `.github/workflows/docker-build.yml`：

```yaml
on:
  push:
    branches:
      - main
      - master
      - feature/3.0.0
      - develop   # 新增
```

### 6.2 工作流文件位置

- `.github/workflows/docker-build.yml`
- 构建使用 `Dockerfile.lsp`（含 JDT LS、Maven、Gradle，完整 v3.0.0 能力）

## 七、查看构建状态

- 仓库 → **Actions** → 选择 **Build and Push Docker Image** 工作流
- 查看每次构建的日志与状态

## 八、故障排查

| 问题 | 可能原因 | 处理 |
|------|----------|------|
| 构建失败 | Dockerfile 路径错误 | 确认 context 为 `.`，file 为 `root_seeker_docker/Dockerfile.lsp` |
| 推送 403 / 401 | Secret 未配置或 Token 无效 | 检查 DOCKERHUB_USERNAME、DOCKERHUB_TOKEN 是否正确 |
| 镜像体积过大 | 依赖过多 | 检查 `.dockerignore` 是否排除无关文件 |

---

*文档维护：RootSeeker Team*
