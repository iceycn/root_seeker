# RootSeeker Docker 镜像（不包含 Qdrant/Zoekt/Admin，需配合 docker-compose）
# 含 zoekt-index，供 POST /index/zoekt/{service_name} 建索引
FROM golang:1.22-alpine AS zoekt-builder
ENV GOPROXY=https://goproxy.cn,direct
RUN go install github.com/google/zoekt/cmd/zoekt-index@latest

FROM python:3.11-slim

WORKDIR /app

# 安装 Git（仓库同步 POST /repos/sync 需要）
RUN apt-get update && apt-get install -y --no-install-recommends git \
    && rm -rf /var/lib/apt/lists/*

# 从 zoekt 构建阶段拷贝 zoekt-index（供 Zoekt 索引 API 使用）
COPY --from=zoekt-builder /go/bin/zoekt-index /usr/local/bin/

# 安装依赖（.dockerignore 已排除无关文件）
COPY . .
RUN pip install --no-cache-dir -e ".[mysql]" && pip cache purge

# 默认配置（可挂载 config.yaml 覆盖）
ENV ROOT_SEEKER_CONFIG_PATH=/app/config.yaml

EXPOSE 8000

CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8000"]
