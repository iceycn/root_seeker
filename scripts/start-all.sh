#!/usr/bin/env bash
# 启动 Qdrant、Zoekt、RootSeeker（各开一个终端，或后台运行）
# 使用方式：在项目根目录执行  bash scripts/start-all.sh

set -e
cd "$(dirname "$0")/.."

PROJECT_ROOT="$(pwd)"
INDEX_DIR="${PROJECT_ROOT}/data/zoekt/index"
GOBIN="$(go env GOPATH 2>/dev/null)/bin"

echo "=== 启动说明 ==="
echo ""
echo "需要开 3 个终端（或后台运行）："
echo ""
echo "1. Qdrant:"
echo "   ./tools/qdrant --config-path config/qdrant_config.yaml"
echo ""
echo "2. Zoekt（需先执行 bash scripts/index-zoekt-all.sh 建索引，-rpc 启用 JSON API）:"
echo "   ${GOBIN}/zoekt-webserver -index ${INDEX_DIR} -listen :6070 -rpc"
echo ""
echo "3. 应用:"
echo "   python3 -m uvicorn main:app --host 0.0.0.0 --port 8000"
echo ""
echo "   开发模式（代码变更自动重启）:"
echo "   bash scripts/start-dev.sh"
echo ""
echo "验证: bash scripts/check-services.sh"
