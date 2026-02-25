#!/usr/bin/env bash
# 检查 Zoekt 与 Qdrant 是否已启动（在项目根目录执行）

set -e
cd "$(dirname "$0")/.."

QDRANT_URL="${QDRANT_URL:-http://127.0.0.1:6333}"
ZOOKT_URL="${ZOOKT_URL:-http://127.0.0.1:6070}"

echo "=== 服务状态 ==="

# Qdrant
if curl -s -o /dev/null -w "%{http_code}" --connect-timeout 2 "$QDRANT_URL/collections" | grep -q 200; then
  echo "Qdrant (6333): 已启动"
  curl -s "$QDRANT_URL/collections" | head -1
else
  echo "Qdrant (6333): 未启动"
  echo "  启动: ./tools/qdrant --config-path config/qdrant_config.yaml"
fi

# Zoekt
if curl -s -o /dev/null -w "%{http_code}" --connect-timeout 2 "$ZOOKT_URL" 2>/dev/null | grep -q 200; then
  echo "Zoekt (6070): 已启动"
else
  echo "Zoekt (6070): 未启动"
  if command -v zoekt-webserver &>/dev/null; then
    echo "  已安装 zoekt-webserver，可用: zoekt-webserver -index <索引目录> -listen :6070"
  else
    GOBIN="$(go env GOPATH 2>/dev/null)/bin"
    if [[ -x "$GOBIN/zoekt-webserver" ]]; then
      echo "  已安装于 $GOBIN，可用: $GOBIN/zoekt-webserver -index <索引目录> -listen :6070"
    else
      echo "  未安装，可执行: go install github.com/google/zoekt/cmd/zoekt-webserver@latest"
    fi
  fi
fi
