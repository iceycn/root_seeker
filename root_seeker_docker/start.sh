#!/usr/bin/env bash
# RootSeeker Docker 一键启动（开箱即用）
# 用法: 在项目根目录执行  bash root_seeker_docker/start.sh

set -e
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
cd "$PROJECT_ROOT"

CONFIG="$PROJECT_ROOT/config.yaml"
CONFIG_EXAMPLE="$PROJECT_ROOT/config.example.yaml"
CONFIG_DOCKER="$SCRIPT_DIR/config.docker.yaml"

# 1. 若 config.yaml 不存在，从 config.example.yaml 复制
if [[ ! -f "$CONFIG" ]]; then
  echo "config.yaml 不存在，从 config.example.yaml 复制..."
  cp "$CONFIG_EXAMPLE" "$CONFIG"
  echo "  已创建默认配置，服务可启动。完整功能需编辑 config.yaml 填写 aliyun_sls、llm 等"
fi

# 2. 合并 Docker 专用配置（qdrant、zoekt、config_db、repos 路径）
if command -v python3 &>/dev/null; then
  if python3 "$SCRIPT_DIR/merge_config.py" "$CONFIG" "$CONFIG_DOCKER" 2>/dev/null; then
    echo "已合并 config.docker.yaml（容器内服务地址）"
  fi
fi

# 3. 确保 data 目录存在（RootSeeker 与 Zoekt 挂载需要，repos_from_git 供 Demo 仓库同步）
mkdir -p "$PROJECT_ROOT/data/repos" "$PROJECT_ROOT/data/repos_from_git" "$PROJECT_ROOT/data/audit"

# 4. 启动
echo ""
echo "=== 启动 Docker 服务（MySQL 首次启动将自动初始化表）==="
cd "$SCRIPT_DIR"
docker compose up -d

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
