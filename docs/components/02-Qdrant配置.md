# Qdrant 配置指南

Qdrant 用作代码**向量库**，RootSeeker 在「建向量索引」和「分析时语义检索」时访问。

## 一、配置项说明

在 `config.yaml` 中：

```yaml
qdrant:
  url: "http://127.0.0.1:6333"    # Qdrant 服务地址
  api_key: null                   # 未开启鉴权时保持 null
  collection: "code_chunks"       # 向量集合名称
```

- **url**：Qdrant REST API 地址，默认 6333。
- **api_key**：若 Qdrant 开启鉴权，填 API Key。
- **collection**：存储代码向量的集合名，应用首次索引时会自动创建。

## 二、安装与启动

### 方式一：Docker（推荐生产）

```bash
mkdir -p /data/qdrant_storage

docker run -d \
  --name qdrant \
  -p 6333:6333 \
  -p 6334:6334 \
  -v /data/qdrant_storage:/qdrant/storage:z \
  qdrant/qdrant
```

### 方式二：macOS 二进制（无 Docker）

```bash
# 使用项目内一键安装
bash scripts/install-without-docker.sh
```

或手动下载：

```bash
mkdir -p tools
ARCH=$(uname -m)
case "$ARCH" in
  arm64|aarch64) Q=aarch64-apple-darwin ;;
  x86_64)       Q=x86_64-apple-darwin   ;;
  *) echo "不支持的架构"; exit 1 ;;
esac
curl -sL -o "tools/qdrant-$Q.tar.gz" \
  "https://github.com/qdrant/qdrant/releases/download/v1.16.3/qdrant-$Q.tar.gz"
tar -xzf "tools/qdrant-$Q.tar.gz" -C tools
# 将 qdrant 二进制移到 tools/
chmod +x tools/qdrant
```

### 启动（使用项目配置）

```bash
# 在项目根目录执行
./tools/qdrant --config-path config/qdrant_config.yaml
```

配置文件 `config/qdrant_config.yaml` 中已设置：
- 存储路径：`./data/qdrant_storage`
- HTTP 端口：6333
- gRPC 端口：6334

## 三、代码仓库向量化（建索引）

### 前置条件

1. Qdrant 已启动。
2. 仓库已同步到 `local_dir`（`POST /repos/sync`）。
3. `config.yaml` 中已配置 `qdrant` 和 `embedding`。

### 为单个仓库建索引

```bash
curl -X POST "http://127.0.0.1:8000/index/repo/order-service"
```

返回示例：`{"status":"ok","indexed_chunks":1234}`

### 为所有仓库建索引

```bash
python3 scripts/index-all-repos.py
```

或带参数：

```bash
python3 scripts/index-all-repos.py --base http://127.0.0.1:8000
python3 scripts/index-all-repos.py --dry-run   # 仅打印，不执行
python3 scripts/index-all-repos.py --api-key YOUR_KEY   # 若配置了鉴权
```

## 四、验证

### 检查 Qdrant 连接

```bash
curl -s http://127.0.0.1:6333/collections
```

返回 JSON 即表示正常。Web UI：`http://127.0.0.1:6333/dashboard`

### 诊断向量索引状态

```bash
python3 scripts/check-vector-index.py
```

会检查：
1. Qdrant 是否可达
2. collection 是否存在
3. 向量数量
4. service_name 分布

指定服务检查：

```bash
python3 scripts/check-vector-index.py --service order-service
```

## 五、向量索引流程说明

1. 应用读取 `local_dir` 下的代码文件。
2. 使用 Tree-sitter 解析，按函数/类等切分为代码块。
3. 使用 Embedding 模型将代码块转为向量。
4. 写入 Qdrant，payload 含：`service_name`、`repo_local_dir`、`file_path`、`start_line`、`end_line`、`text`。

分析时，`VectorRetriever` 按 `service_name` 过滤后做向量检索。

## 六、常见问题

### 向量检索为 0

1. 运行 `python3 scripts/check-vector-index.py` 诊断。
2. 确认该 `service_name` 已执行过索引：`POST /index/repo/{service_name}`。
3. 确认 config 中 `service_name` 与索引时一致（注意 K8s pod 名如 `xxx-7d8f9c` 会归一化为 `xxx`）。

### 索引很慢

- 首次会加载 Embedding 模型，可能较慢。
- 大仓库可考虑分批或限制目录（`call_graph_scan_limit_dirs`）。

### 生产建议

- 开启 Qdrant API Key 鉴权。
- 定期备份 `data/qdrant_storage`）。
- 根据仓库规模预留足够内存与磁盘。

[English](en/02-qdrant.md)
