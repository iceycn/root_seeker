# RootSeeker Docker 镜像（v3.0.0：含 JDT LS + Python LSP + Maven + Gradle）
# 支持 LSP、cmd.run_build_analysis、deps.fetch_java_sources 等 v3.0 能力
# 构建：docker build -f root_seeker_docker/Dockerfile.lsp -t root-seeker:lsp .
FROM golang:1.22-alpine AS zoekt-builder
RUN export GOPROXY=https://goproxy.cn,direct GOTOOLCHAIN=auto; go install github.com/sourcegraph/zoekt/cmd/zoekt-index@latest

# 使用 bookworm 确保 openjdk-17-jdk 在 main 仓库可用（bullseye 需 backports）
FROM python:3.11-slim-bookworm

LABEL version="3.0.0"
LABEL description="RootSeeker v3.0.0 - AI-powered error analysis with LSP, Maven, Gradle"

WORKDIR /app

# 安装 Git、curl、OpenJDK、Maven、unzip（JDT LS、cmd.run_build_analysis 需要）
RUN apt-get update && apt-get install -y --no-install-recommends \
    git openssh-client curl openjdk-17-jdk maven unzip \
    && rm -rf /var/lib/apt/lists/*

# Gradle（cmd.run_build_analysis、deps 解析需要）
ARG GRADLE_VERSION=8.5
RUN curl -fsSL "https://services.gradle.org/distributions/gradle-${GRADLE_VERSION}-bin.zip" -o /tmp/gradle.zip \
    && unzip -q /tmp/gradle.zip -d /opt \
    && ln -sf /opt/gradle-${GRADLE_VERSION}/bin/gradle /usr/local/bin/gradle \
    && rm /tmp/gradle.zip

# JDT LS：版本固定（修改下方版本与 URL 即切换）
ARG JDTLS_VERSION=1.38.0
ARG JDTLS_ARCHIVE=jdt-language-server-1.38.0-202408011337.tar.gz
# JDT LS 解压（归档含一层版本目录，扁平化到 /opt/jdtls）
RUN mkdir -p /opt/jdtls \
    && curl -fsSL "https://download.eclipse.org/jdtls/milestones/${JDTLS_VERSION}/${JDTLS_ARCHIVE}" \
    | tar -xz -C /opt/jdtls \
    && subdir=$(find /opt/jdtls -maxdepth 1 -type d -name 'jdt-language-server-*' 2>/dev/null | head -1) \
    && [ -n "$$subdir" ] && mv "$$subdir"/* /opt/jdtls/ && rmdir "$$subdir" 2>/dev/null; true

# 从 zoekt 构建阶段拷贝 zoekt-index
COPY --from=zoekt-builder /go/bin/zoekt-index /usr/local/bin/

# 安装 RootSeeker 及 LSP 依赖（python-lsp-server 版本在 pyproject.toml 固定）
COPY . .
RUN pip install --no-cache-dir -e ".[mysql,lsp]" -i https://mirrors.aliyun.com/pypi/simple/ && pip cache purge

ENV ROOT_SEEKER_CONFIG_PATH=/app/config.yaml
ENV JDTLS_HOME=/opt/jdtls

EXPOSE 8000

CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8000"]
