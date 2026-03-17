#!/usr/bin/env bash
# RootSeeker Docker 一键启动（开箱即用）
# 用法: 在项目根目录执行  bash root_seeker_docker/start.sh
#       bash root_seeker_docker/start.sh --pull   # 使用预构建镜像（ghcr.io），无需本地构建

set -e
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
cd "$PROJECT_ROOT"

CONFIG_DOCKER="$SCRIPT_DIR/config.docker.yaml"
if [[ ! -f "$CONFIG_DOCKER" ]]; then
  echo "缺少 config.docker.yaml，无法启动 Docker 编排"
  exit 1
fi

# 1. 确保 data 目录存在（RootSeeker 与 Zoekt 挂载需要，repos_from_git 供 Demo 仓库同步）
mkdir -p "$PROJECT_ROOT/data/repos" "$PROJECT_ROOT/data/repos_from_git" "$PROJECT_ROOT/data/audit"

# 2. 启动
USE_PULL=false
[[ "$1" == "--pull" ]] && USE_PULL=true

cd "$SCRIPT_DIR"
if [[ "$USE_PULL" == true ]]; then
  echo ""
  echo "=== 启动 Docker 服务（使用预构建镜像 ghcr.io/iceycn/root-seeker:latest）==="
  # 先构建 zoekt、admin（root-seeker 用预构建镜像）
  docker compose build zoekt root-seeker-admin
  docker compose -f docker-compose.yml -f docker-compose.pull.yml up -d --no-build
else
  echo ""
  echo "=== 启动 Docker 服务（本地构建，MySQL 首次启动将自动初始化表）==="
  docker compose up -d --build
fi

echo ""
echo "=== 服务已启动 ==="
echo "  RootSeeker:     http://localhost:8000"
echo "  RootSeeker Admin: http://localhost:8088  （默认 admin/admin123，AI应用配置在 Git源码管理 下）"
echo "  Qdrant:         http://localhost:6333"
echo "  Zoekt:          http://localhost:6070"
echo ""
echo "健康检查: curl http://localhost:8000/healthz"
echo "查看日志: cd root_seeker_docker && docker compose logs -f"
echo "停止服务: cd root_seeker_docker && docker compose down"
