#!/bin/bash
# 模拟 remove_qdrant 和 remove_zoekt 回调，验证 Admin 状态更新
# 用法: bash scripts/test-callback-remove.sh [ADMIN_URL]
# 默认: http://localhost:8080

BASE="${1:-http://localhost:8080}"
CB="${BASE}/gitsource/index/callback"

echo "=== 模拟 remove 回调 (Admin=$BASE) ==="

# 1. 先设为已索引
echo "1. 设为已索引..."
curl -s -X POST "$CB" -H "Content-Type: application/json" \
  -d '{"service_name":"api-distribution","task_type":"qdrant","status":"completed","qdrant_indexed":1,"qdrant_count":100}'
echo ""
curl -s -X POST "$CB" -H "Content-Type: application/json" \
  -d '{"service_name":"api-distribution","task_type":"zoekt","status":"completed","zoekt_indexed":1}'
echo ""

# 2. 模拟 remove（并发）
echo "2. 发送 remove_qdrant 和 remove_zoekt..."
curl -s -X POST "$CB" -H "Content-Type: application/json" \
  -d '{"service_name":"api-distribution","task_type":"remove_qdrant","status":"completed","qdrant_indexed":0}'
echo ""
curl -s -X POST "$CB" -H "Content-Type: application/json" \
  -d '{"service_name":"api-distribution","task_type":"remove_zoekt","status":"completed","zoekt_indexed":0}'
echo ""

echo "=== 完成。请在 Admin 仓库管理页查看 api-distribution 的 Qdrant/Zoekt 是否显示「未索引」 ==="
