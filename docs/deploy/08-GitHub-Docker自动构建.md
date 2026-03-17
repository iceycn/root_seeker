# GitHub 自动构建 Docker 镜像

## 一、概述

项目已配置 GitHub Actions 工作流，在推送代码时自动构建 RootSeeker Docker 镜像并推送到 **GitHub Container Registry (ghcr.io)**。

## 二、触发条件

| 事件 | 触发分支/标签 | 是否推送镜像 |
|------|---------------|--------------|
| `push` | `main`、`master`、`feature/3.0.0` | ✅ 是 |
| `push` | 标签 `v*`（如 v3.0.0） | ✅ 是 |
| `pull_request` | 目标为 main/master | ❌ 否（仅构建验证） |

## 三、镜像地址与标签

- **基础地址**：`ghcr.io/<你的GitHub用户名>/root-seeker`
- **示例**：`ghcr.io/iceycn/root-seeker`

| 触发方式 | 示例标签 |
|----------|----------|
| 推送到 main | `latest` |
| 推送到 feature/3.0.0 | `feature-3.0.0` |
| 推送标签 v3.0.0 | `v3.0.0`、`3.0.0` |
| 任意提交 | `sha-<short_sha>` |

## 四、使用方式

### 4.1 拉取镜像

```bash
# 拉取最新版（main 分支）
docker pull ghcr.io/iceycn/root-seeker:latest

# 拉取指定版本
docker pull ghcr.io/iceycn/root-seeker:v3.0.0

# 拉取 feature 分支
docker pull ghcr.io/iceycn/root-seeker:feature-3.0.0
```

### 4.2 首次拉取：登录 ghcr.io

若镜像为私有，需先登录：

```bash
echo $GITHUB_TOKEN | docker login ghcr.io -u <你的GitHub用户名> --password-stdin
```

`GITHUB_TOKEN` 需有 `read:packages` 权限。创建方式：GitHub → Settings → Developer settings → Personal access tokens → 勾选 `read:packages`。

若镜像为公开，无需登录即可拉取。

### 4.3 修改镜像可见性

1. 打开 GitHub 仓库 → **Packages** 右侧
2. 点击 `root-seeker` 包
3. **Package settings** → **Change visibility** → 选择 **Public** 或 **Private**

## 五、配置说明

### 5.1 无需额外配置

- 使用 `GITHUB_TOKEN`（Actions 自动注入），无需创建 Secret
- 推送至 ghcr.io 无需 Docker Hub 账号

### 5.2 增加触发分支

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

### 5.3 同时推送到 Docker Hub（可选）

如需推送到 Docker Hub，需在仓库配置 Secret：

1. 仓库 → **Settings** → **Secrets and variables** → **Actions**
2. 新增 Secret：
   - `DOCKERHUB_USERNAME`：Docker Hub 用户名
   - `DOCKERHUB_TOKEN`：Docker Hub Access Token（在 hub.docker.com 创建）

3. 在 workflow 中增加：

```yaml
      - name: Log in to Docker Hub
        if: github.event_name != 'pull_request'
        uses: docker/login-action@v3
        with:
          username: ${{ secrets.DOCKERHUB_USERNAME }}
          password: ${{ secrets.DOCKERHUB_TOKEN }}

      # 在 metadata 的 images 中增加一行
      # images: |
      #   ghcr.io/${{ github.repository_owner }}/root-seeker
      #   ${{ secrets.DOCKERHUB_USERNAME }}/root-seeker
```

## 六、工作流文件位置

- `.github/workflows/docker-build.yml`
- 构建使用 `Dockerfile.lsp`（含 JDT LS、Maven、Gradle，完整 v3.0.0 能力）

## 七、查看构建状态

- 仓库 → **Actions** → 选择 **Build and Push Docker Image** 工作流
- 查看每次构建的日志与状态

## 八、故障排查

| 问题 | 可能原因 | 处理 |
|------|----------|------|
| 构建失败 | Dockerfile 路径错误 | 确认 context 为 `.`，file 为 `root_seeker_docker/Dockerfile.lsp` |
| 推送 403 | 权限不足 | 检查 `packages: write` 权限 |
| 拉取 401 | 需登录 | 使用 PAT 登录 ghcr.io |
| 镜像体积过大 | 依赖过多 | 检查 `.dockerignore` 是否排除无关文件 |

---

*文档维护：RootSeeker Team*
