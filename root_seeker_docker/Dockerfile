# RootSeeker Docker 镜像（不包含 Qdrant/Zoekt/Admin，需配合 docker-compose）
FROM python:3.11-slim

WORKDIR /app

# 安装依赖（.dockerignore 已排除无关文件）
COPY . .
RUN pip install --no-cache-dir -e ".[mysql]" && pip cache purge

# 默认配置（可挂载 config.yaml 覆盖）
ENV ROOT_SEEKER_CONFIG_PATH=/app/config.yaml

EXPOSE 8000

CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8000"]
