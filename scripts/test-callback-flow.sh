#!/bin/bash
# 完整测试回调流程：发送所有 task_type 到 /gitsource/index/callback
# 用法: bash scripts/test-callback-flow.sh [ADMIN_URL]
# 默认: http://localhost:8080
# 前置: Admin 需已启动，日志中可搜索 [IndexCallback] 验证

BASE="${1:-http://localhost:8080}"
CB="${BASE}/gitsource/index/callback"

echo "=========================================="
echo "  回调流程测试 - 覆盖所有事件类型 (Admin=$BASE)"
echo "  请在 Admin 日志中搜索: [IndexCallback]"
echo "=========================================="

test_cb() {
  local name="$1"
  local payload="$2"
  echo ""
  echo ">>> $name"
  echo "    payload: $payload"
  resp=$(curl -s -w "\n%{http_code}" -X POST "$CB" -H "Content-Type: application/json" -d "$payload")
  body=$(echo "$resp" | sed '$d')
  code=$(echo "$resp" | tail -1)
  echo "    response: $body (HTTP $code)"
}

# 使用统一 service_name 便于按顺序验证
SN="all-events-test"

# --- qdrant ---
test_cb "1. qdrant completed" "{\"service_name\":\"$SN\",\"task_type\":\"qdrant\",\"status\":\"completed\",\"qdrant_indexed\":1,\"qdrant_count\":50}"
test_cb "2. qdrant failed" "{\"service_name\":\"$SN\",\"task_type\":\"qdrant\",\"status\":\"failed\"}"

# --- zoekt ---
test_cb "3. zoekt completed" "{\"service_name\":\"$SN\",\"task_type\":\"zoekt\",\"status\":\"completed\",\"zoekt_indexed\":1}"
test_cb "4. zoekt failed" "{\"service_name\":\"$SN\",\"task_type\":\"zoekt\",\"status\":\"failed\"}"

# --- remove_qdrant ---
test_cb "5. remove_qdrant completed" "{\"service_name\":\"$SN\",\"task_type\":\"remove_qdrant\",\"status\":\"completed\",\"qdrant_indexed\":0}"
test_cb "6. remove_qdrant failed" "{\"service_name\":\"$SN\",\"task_type\":\"remove_qdrant\",\"status\":\"failed\"}"

# --- remove_zoekt ---
test_cb "7. remove_zoekt completed" "{\"service_name\":\"$SN\",\"task_type\":\"remove_zoekt\",\"status\":\"completed\",\"zoekt_indexed\":0}"
test_cb "8. remove_zoekt failed" "{\"service_name\":\"$SN\",\"task_type\":\"remove_zoekt\",\"status\":\"failed\"}"

# --- resync ---
test_cb "9. resync completed" "{\"service_name\":\"$SN\",\"task_type\":\"resync\",\"status\":\"completed\",\"qdrant_indexed\":1,\"qdrant_count\":80,\"zoekt_indexed\":1}"
test_cb "10. resync failed" "{\"service_name\":\"$SN\",\"task_type\":\"resync\",\"status\":\"failed\"}"

# --- sync ---
test_cb "11. sync completed" "{\"service_name\":\"$SN\",\"task_type\":\"sync\",\"status\":\"completed\",\"qdrant_indexed\":true,\"qdrant_indexing\":false,\"qdrant_count\":100,\"zoekt_indexed\":true,\"zoekt_indexing\":false}"

# --- 边界 ---
test_cb "12. 空 service_name (应忽略)" '{"service_name":"","task_type":"qdrant","status":"completed"}'
test_cb "13. 空 payload" '{}'

echo ""
echo "=========================================="
echo "  测试完成。请检查 Admin 日志："
echo "  - [IndexCallback] ========== 收到 /gitsource/index/callback 请求"
echo "  - [IndexCallback] 入队: service_name=..."
echo "  - [RepoIndexStatus] 开始处理回调..."
echo "  - [RepoIndexStatus] 已持久化(qdrant|zoekt|remove_qdrant|remove_zoekt|resync|sync)"
echo "=========================================="
