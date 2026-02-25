#!/usr/bin/env bash
# 清除 Python 字节码缓存，确保使用最新代码
set -e
cd "$(dirname "$0")/.."
find . -type d -name "__pycache__" -exec rm -rf {} + 2>/dev/null || true
find . -name "*.pyc" -delete 2>/dev/null || true
echo "Python 缓存已清除"
