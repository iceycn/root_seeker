# LSP（JDT LS / Pyright）Docker 部署说明

v3.0.0 要求：将 JDT LS / Pyright（或 python-lsp-server）**内置进镜像**，且**版本固定**（镜像 tag 即版本）。禁止运行时临时联网下载二进制。

## 1. 概述

| 语言 | 默认 LSP | 备选 | 版本固定方式 |
|------|----------|------|--------------|
| Java | JDT LS | - | 镜像构建时下载指定 milestone |
| Python | python-lsp-server (pylsp) | Pyright | pip 固定版本 |

## 2. Python LSP（pylsp / Pyright）

### 2.1 默认：python-lsp-server

RootSeeker 已通过 `pip install -e ".[lsp]"` 安装 `python-lsp-server>=1.7`，Docker 镜像只需在 `pip install` 时加上 `lsp` extra：

```dockerfile
RUN pip install --no-cache-dir -e ".[mysql,lsp]" -i https://mirrors.aliyun.com/pypi/simple/
```

版本在 `pyproject.toml` 中固定：`python-lsp-server>=1.7`。

### 2.2 可选：Pyright

若需使用 Pyright 替代 pylsp，在 `lsp.start` 的 `extra` 中指定：

```json
{
  "lsp_command": ["python", "-m", "pyright_langserver", "--stdio"]
}
```

需在镜像中预装：

```dockerfile
RUN pip install pyright
```

建议固定版本，例如：`pyright==1.1.350`。

## 3. Java LSP（JDT LS）

### 3.1 下载与版本

- **下载地址**：https://download.eclipse.org/jdtls/milestones/
- **推荐版本**：1.38.0（2024-08-01）或更新 milestone，如 1.42.0
- **格式**：`jdt-language-server-<version>-<timestamp>.tar.gz`，解压后包含 `plugins/`、`config_linux`、`config_mac`、`config_win`

### 3.2 示例 Dockerfile

```dockerfile
# 在 root_seeker_docker/Dockerfile 基础上增加 JDT LS 层
FROM python:3.11-slim

# ... 省略 zoekt、git、pip 等安装 ...

# JDT LS：版本固定（修改 JDTLS_VERSION 即切换版本）
ARG JDTLS_VERSION=1.38.0
ARG JDTLS_URL=https://download.eclipse.org/jdtls/milestones/${JDTLS_VERSION}/jdt-language-server-${JDTLS_VERSION}-202408011337.tar.gz

RUN apt-get update && apt-get install -y --no-install-recommends \
    curl \
    openjdk-17-jdk \
    && mkdir -p /opt/jdtls \
    && curl -fsSL "${JDTLS_URL}" | tar -xz -C /opt/jdtls \
    && apt-get remove -y curl && apt-get autoremove -y \
    && rm -rf /var/lib/apt/lists/*

ENV JDTLS_HOME=/opt/jdtls
# 查找 launcher jar（版本号可能变化）
ENV JDTLS_LAUNCHER="org.eclipse.equinox.launcher_1.4.0.v20161219-1356.jar"
# 实际构建时可用 RUN find /opt/jdtls/plugins -name 'org.eclipse.equinox.launcher_*.jar' 获取
```

**注意**：`jdt-language-server-1.38.0-202408011337.tar.gz` 中的时间戳需与 [milestones 目录](https://download.eclipse.org/jdtls/milestones/1.38.0/) 实际文件名一致，不同版本时间戳不同。

### 3.3 lsp.start.extra 配置

```json
{
  "jdtls_launcher_path": "/opt/jdtls/plugins/org.eclipse.equinox.launcher_1.4.0.v20161219-1356.jar",
  "jdtls_config_dir": "/opt/jdtls/config_linux",
  "workspace_data_dir": "/tmp/jdtls_workspace"
}
```

- `config_linux`：Linux 容器用；`config_mac`、`config_win` 对应 macOS/Windows
- `workspace_data_dir`：需可写，建议挂载卷或使用 `/tmp` 下的持久化目录

### 3.4 多版本兼容

launcher jar 版本号随 JDT LS 变化，构建时可用脚本动态查找：

```dockerfile
RUN LAUNCHER=$(find /opt/jdtls/plugins -name 'org.eclipse.equinox.launcher_*.jar' | head -1) \
    && echo "JDTLS_LAUNCHER=${LAUNCHER}" > /opt/jdtls/launcher_path
```

运行时读取该文件或通过环境变量传入 `jdtls_launcher_path`。

## 4. 完整 Dockerfile.lsp

见 `root_seeker_docker/Dockerfile.lsp`。构建：

```bash
docker build -f root_seeker_docker/Dockerfile.lsp -t root-seeker:lsp .
```

## 5. 配置来源

- **数据库模式**：`app_config` 表中 `repo_config` 的 `extra` 字段可包含 `jdtls_launcher_path`、`jdtls_config_dir`、`workspace_data_dir`、`lsp_command` 等
- **YAML 模式**：`config.yaml` 中 `repos[].extra` 可配置上述字段

## 6. 验证

- **Python**：`lsp.start` 传入 `language=python`、`repo_id`，成功后调用 `lsp.document_symbols` 应有返回
- **Java**：`lsp.start` 传入 `language=java`、`repo_id`，成功后调用 `lsp.definition` 应有返回

## 7. 版本对照表

| 组件 | 推荐版本 | 说明 |
|------|----------|------|
| JDT LS | 1.38.0 / 1.42.0 | 需 Java 17+ |
| python-lsp-server | >=1.7 | pyproject.toml lsp extra |
| Pyright | 1.1.350+ | 可选，需显式 lsp_command |
