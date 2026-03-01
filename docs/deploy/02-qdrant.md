# Qdrant 傻瓜部署

Qdrant 用作代码向量库，RootSeeker 在「建向量索引」和「分析时语义检索」时访问。

> **安装指南**：若需从零安装 Qdrant，见 [依赖组件安装指南](../INSTALL_DEPENDENCIES.md#二qdrant-安装)。

## 1. 适用环境

- 内网 Linux 服务器（或 macOS 开发机）
- Docker 可用，或使用官方二进制

## 2. Docker 部署（推荐）

```bash
# 创建持久化目录
mkdir -p /data/qdrant_storage

# 单机运行（HTTP 6333，gRPC 6334）
docker run -d \
  --name qdrant \
  -p 6333:6333 \
  -p 6334:6334 \
  -v /data/qdrant_storage:/qdrant/storage:z \
  qdrant/qdrant
```

- **6333**：REST API，RootSeeker 使用该端口。
- **6334**：gRPC（可选，本应用未用）。
- 存储目录需为本地块设备或 POSIX 文件系统，不要用 NFS/S3 作为主存储。

## 3. 验证

```bash
curl -s http://127.0.0.1:6333/collections
```

返回 JSON（含 collections 列表）即表示服务正常。  
Web UI：`http://127.0.0.1:6333/dashboard`（若网络可达）。

## 4. 与 RootSeeker 的对应

- 在 `config.yaml` 中配置：

```yaml
qdrant:
  url: "http://<Qdrant 主机>:6333"
  api_key: null   # 未开启鉴权时保持 null
  collection: "code_chunks"
```

- 应用首次对某仓库执行 `POST /index/repo/{service_name}` 时，会按 embedding 维度自动创建 collection `code_chunks`（若不存在），并写入向量与 payload（service_name、file_path、start_line、end_line、text 等）。
- 分析时 `VectorRetriever` 会按 `service_name`（及可选 repo_local_dir）过滤后做向量检索。

## 5. 生产注意

- **鉴权**：Qdrant 支持 API Key，生产建议开启并在 `config.yaml` 中配置 `qdrant.api_key`。
- **资源**：向量量与维度决定内存与磁盘，可根据仓库数量与 chunk 规模预留资源。
- **备份**：定期备份 `/data/qdrant_storage`（或实际挂载目录）。

## 6. macOS 二进制安装（无 Docker，推荐本机开发）

无需 Docker，直接使用官方预编译包：

```bash
# 在项目根目录执行（或使用 scripts/install-without-docker.sh）
mkdir -p tools
ARCH=$(uname -m)
case "$ARCH" in
  arm64|aarch64) Q=aarch64-apple-darwin ;;
  x86_64)       Q=x86_64-apple-darwin   ;;
  *) echo "不支持的架构: $ARCH"; exit 1 ;;
esac
curl -sL -o "tools/qdrant-$Q.tar.gz" \
  "https://github.com/qdrant/qdrant/releases/download/v1.16.3/qdrant-$Q.tar.gz"
tar -xzf "tools/qdrant-$Q.tar.gz" -C tools
rm "tools/qdrant-$Q.tar.gz"
# 若解压出的是子目录，将二进制移到 tools/qdrant
[[ -f tools/qdrant ]] || mv "tools/qdrant-$Q/qdrant" tools/qdrant
chmod +x tools/qdrant
```

启动（使用项目内配置，数据目录为 `data/qdrant_storage`）：

```bash
# 在项目根目录执行
./tools/qdrant --config-path config/qdrant_config.yaml
```

配置文件 `config/qdrant_config.yaml` 中已设置 `storage.storage_path: ./data/qdrant_storage`。默认监听 6333（HTTP）、6334（gRPC）。
