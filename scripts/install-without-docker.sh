#!/usr/bin/env bash
# 在当前机器上安装 RootSeeker 依赖组件（不依赖 Docker）
# 使用方式：在项目根目录执行  bash scripts/install-without-docker.sh

set -e
cd "$(dirname "$0")/.."
PROJECT_ROOT="${PWD}"
TOOLS_DIR="${PROJECT_ROOT}/tools"
QDRANT_VERSION="${QDRANT_VERSION:-v1.16.3}"

echo "=== 1. Python 依赖（RootSeeker）==="
pip3 install -e .

echo ""
echo "=== 2. Go（用于 Zoekt）==="
if ! command -v go &>/dev/null; then
  if command -v brew &>/dev/null; then
    brew install go
  else
    echo "未检测到 Go 和 Homebrew，请先安装: https://go.dev/dl/"
    exit 1
  fi
fi
go version

echo ""
echo "=== 3. Zoekt（词法检索）==="
# 使用 google/zoekt（与 sourcegraph/zoekt API 兼容）
go install github.com/google/zoekt/cmd/zoekt-index@latest
go install github.com/google/zoekt/cmd/zoekt-webserver@latest
echo "Zoekt 已安装到: $(go env GOPATH)/bin"

echo ""
echo "=== 4. Qdrant（向量库，macOS/Linux 二进制，无 Docker）==="
mkdir -p "${TOOLS_DIR}"
ARCH=$(uname -m)
OS=$(uname -s)
case "${OS}" in
  Darwin)
    case "${ARCH}" in
      arm64|aarch64) QDRANT_ARCH="aarch64-apple-darwin" ;;
      x86_64)        QDRANT_ARCH="x86_64-apple-darwin" ;;
      *) echo "macOS 架构 ${ARCH} 未支持"; exit 1 ;;
    esac
    QDRANT_SUFFIX=".tar.gz"
    ;;
  Linux)
    case "${ARCH}" in
      x86_64)  QDRANT_ARCH="x86_64-unknown-linux-gnu" ;;
      aarch64|arm64) QDRANT_ARCH="aarch64-unknown-linux-gnu" ;;
      *) echo "Linux 架构 ${ARCH} 未支持"; exit 1 ;;
    esac
    QDRANT_SUFFIX=".tar.gz"
    ;;
  *)
    echo "当前系统 ${OS} 未提供预编译包，请从 https://github.com/qdrant/qdrant/releases 查看或使用 root_seeker_docker。"
    exit 1
    ;;
esac

QDRANT_TGZ="qdrant-${QDRANT_ARCH}${QDRANT_SUFFIX}"
QDRANT_URL="https://github.com/qdrant/qdrant/releases/download/${QDRANT_VERSION}/${QDRANT_TGZ}"
if [[ ! -f "${TOOLS_DIR}/qdrant" ]]; then
  echo "下载 Qdrant: ${QDRANT_URL}"
  curl -sL -o "${TOOLS_DIR}/${QDRANT_TGZ}" "${QDRANT_URL}"
  tar -xzf "${TOOLS_DIR}/${QDRANT_TGZ}" -C "${TOOLS_DIR}"
  rm -f "${TOOLS_DIR}/${QDRANT_TGZ}"
  # 压缩包可能解压出 qdrant 或 子目录/qdrant
  if [[ -f "${TOOLS_DIR}/qdrant" ]]; then
    : # 已在根目录
  else
    BIN=$(find "${TOOLS_DIR}" -maxdepth 2 -name qdrant -type f 2>/dev/null | head -1)
    if [[ -n "${BIN}" ]]; then
      mv "${BIN}" "${TOOLS_DIR}/qdrant"
      find "${TOOLS_DIR}" -mindepth 1 -maxdepth 1 -type d -exec rm -rf {} + 2>/dev/null || true
    fi
  fi
  echo "Qdrant 二进制已解压到: ${TOOLS_DIR}/qdrant"
else
  echo "已存在 ${TOOLS_DIR}/qdrant，跳过下载"
fi
chmod +x "${TOOLS_DIR}/qdrant" 2>/dev/null || true

echo ""
echo "=== 安装完成 ==="
echo ""
echo "后续步骤："
echo "  1. 复制配置: cp config.example.yaml config.yaml  并修改 config.yaml"
echo "  2. 启动 Qdrant（在项目根目录）:"
echo "     ${TOOLS_DIR}/qdrant --config-path config/qdrant_config.yaml"
echo "  3. 若有本地仓库，为 Zoekt 建索引并启动:"
echo "     zoekt-webserver -index /path/to/zoekt_index -listen :6070"
echo "  4. 启动应用: python3 -m uvicorn main:app --host 0.0.0.0 --port 8000"
echo ""
echo "将 Zoekt 加入 PATH（可选）: export PATH=\"\$(go env GOPATH)/bin:\$PATH\""
echo "将 Qdrant 加入 PATH（可选）: export PATH=\"${TOOLS_DIR}:\$PATH\""
