#!/usr/bin/env bash
# 直接调用：提交钉钉那条 SLS 日志到 RootSeeker，无需外部文件
# 用法: bash scripts/curl-ingest-dingtalk-direct.sh [BASE_URL]
BASE="${1:-http://127.0.0.1:8000}"
curl -s -X POST "$BASE/ingest/aliyun-sls" -H "Content-Type: application/json" -d @- <<'JSON'
{"service_name": "enterprise-manage-api", "error_log": "2026-02-03 11:54:08.532 enterprise-manage-api [DefaultMessageListenerContainer-9] ERROR topsdk - [,,c838ec37cd8c4a899c00ed27d0d5dc4e],2026-02-03 11:54:08.532^_^_dingtalk_^_^dingtalk.oapi.user.get^_^10.105.4.30^_^Linux^_^184^_^https://oapi.dingtalk.com/user/get^_^access_token=a66a6ea36ac435aab70e279c9386d6fd&userid=370866416138015516^_^{\"errcode\":50002,\"errmsg\":\"请求的员工userid不在授权范围内\"}", "query_key": "default_error_context", "timestamp": null, "tags": {}}
JSON
