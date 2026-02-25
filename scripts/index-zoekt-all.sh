#!/usr/bin/env bash
# 根据 config.yaml 中的 repos 为所有仓库建 Zoekt 索引
# 使用方式：在项目根目录执行  bash scripts/index-zoekt-all.sh

set -e
cd "$(dirname "$0")/.."

INDEX_DIR="${ZOOKT_INDEX_DIR:-$(pwd)/data/zoekt/index}"
ZOOKT_INDEX="${ZOOKT_INDEX:-$(go env GOPATH 2>/dev/null)/bin/zoekt-index}"

if [[ ! -x "$ZOOKT_INDEX" ]]; then
  echo "zoekt-index 未找到，请先执行: go install github.com/sourcegraph/zoekt/cmd/zoekt-index@latest"
  exit 1
fi

mkdir -p "$INDEX_DIR"
echo "Zoekt 索引目录: $INDEX_DIR"
echo ""

# 从 config.yaml 提取 local_dir（简单解析，假设格式规范）
count=0
while IFS= read -r line; do
  if [[ "$line" =~ local_dir:[[:space:]]*\"([^\"]+)\" ]]; then
    dir="${BASH_REMATCH[1]}"
    if [[ -d "$dir" ]]; then
      name=$(basename "$dir")
      echo "[$((++count))] 索引: $name -> $dir"
      "$ZOOKT_INDEX" -index "$INDEX_DIR" "$dir" || echo "  跳过（可能已索引）"
    else
      echo "[跳过] $dir 不存在"
    fi
  fi
done < <(grep -E "local_dir:" config.yaml 2>/dev/null || true)

echo ""
echo "索引完成。启动 zoekt-webserver（-rpc 启用 JSON API，供 RootSeeker 调用）:"
echo "  $(dirname "$ZOOKT_INDEX")/zoekt-webserver -index $INDEX_DIR -listen :6070 -rpc"
echo "或（若 go/bin 在 PATH 中）:"
echo "  zoekt-webserver -index $INDEX_DIR -listen :6070"
