#!/usr/bin/env bash
# 使用 curl 提交钉钉那条 SLS 日志到 RootSeeker 分析
# 依赖：请求体已生成到 data/ingest_body_dingtalk.json（可由 scripts/ingest-one-sls-log.py 解析 SLS 原始日志得到）
# 用法: bash scripts/curl-ingest-dingtalk.sh [BASE_URL]

set -e
BASE="${1:-http://127.0.0.1:8000}"
BODY_FILE="data/ingest_body_dingtalk.json"
if [ ! -f "$BODY_FILE" ]; then
  echo "请先生成请求体: python3 -c \"
import json
with open('data/sample_sls_log_dingtalk.json') as f: raw = json.load(f)
with open('data/ingest_body_dingtalk.json', 'w', encoding='utf-8') as f:
  json.dump({'service_name': raw.get('__tag__:_container_name__', 'enterprise-manage-api'), 'error_log': raw.get('content', ''), 'query_key': 'default_error_context', 'timestamp': None, 'tags': {}}, f, ensure_ascii=False)
\""
  exit 1
fi

echo "POST $BASE/ingest/aliyun-sls"
RESP=$(curl -s -X POST "$BASE/ingest/aliyun-sls" \
  -H "Content-Type: application/json" \
  -d @"$BODY_FILE")
echo "$RESP"
AID=$(echo "$RESP" | python3 -c "import sys,json; d=json.load(sys.stdin); print(d.get('analysis_id',''))" 2>/dev/null || true)
if [ -n "$AID" ]; then
  echo ""
  echo "查看结果: curl -s $BASE/analysis/$AID"
fi
