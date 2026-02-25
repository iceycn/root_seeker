# Zoekt 配置指南

Zoekt 用于代码**词法/符号检索**，RootSeeker 分析错误时会调用 Zoekt 快速定位相关代码文件与行号。

## 一、配置项说明

在 `config.yaml` 中：

```yaml
zoekt:
  api_base_url: "http://127.0.0.1:6070"   # Zoekt 服务地址，默认 6070
```

- **api_base_url**：Zoekt webserver 的 HTTP 地址。若部署在其他机器，改为 `http://<主机>:6070`。
- 若不配置 `zoekt` 块（或注释掉），应用将跳过词法检索，仅使用向量检索和堆栈解析。

## 二、安装

### 方式一：Go 安装（推荐）

```bash
# 需要 Go 1.19+
go install github.com/google/zoekt/cmd/zoekt-index@latest
go install github.com/google/zoekt/cmd/zoekt-webserver@latest
```

安装后二进制在 `$(go env GOPATH)/bin`，可加入 PATH：

```bash
export PATH="$(go env GOPATH)/bin:$PATH"
```

### 方式二：一键安装脚本

```bash
bash scripts/install-without-docker.sh
```

脚本会安装 Go、Zoekt、Qdrant 等，按提示将 `go env GOPATH/bin` 加入 PATH。

## 三、仓库初始化与索引

### 1. 准备本地仓库目录

确保 `config.yaml` 中 `repos[].local_dir` 指向的目录存在，且已拉取代码：

```bash
# 同步所有仓库
curl -X POST "http://127.0.0.1:8000/repos/sync"

# 或只同步单个
curl -X POST "http://127.0.0.1:8000/repos/sync?service_name=order-service"
```

### 2. 为所有仓库建索引（脚本）

```bash
# 在项目根目录执行
bash scripts/index-zoekt-all.sh
```

脚本会从 `config.yaml` 读取 `local_dir`，对每个存在的目录执行 `zoekt-index`，索引输出到 `data/zoekt/index`（可通过环境变量 `ZOOKT_INDEX_DIR` 覆盖）。

### 3. 手动为单个仓库建索引

```bash
export ZOOKT_INDEX_DIR=/path/to/zoekt/index
mkdir -p "$ZOOKT_INDEX_DIR"

zoekt-index \
  -index "$ZOOKT_INDEX_DIR" \
  -repo_name "order-service" \
  /data/repos/order-service
```

- **-repo_name**：建议与 `config.yaml` 中 `service_name` 一致，便于按仓库过滤。
- **-index**：索引输出目录，多仓库共用同一目录。
- 最后一个参数：本地仓库路径（与 `local_dir` 一致）。

### 4. 启动 Zoekt 搜索服务

```bash
zoekt-webserver -index data/zoekt/index -listen :6070
```

若 Zoekt 在 `$(go env GOPATH)/bin` 下：

```bash
$(go env GOPATH)/bin/zoekt-webserver -index data/zoekt/index -listen :6070
```

## 四、验证

```bash
curl -s -X POST "http://127.0.0.1:6070/api/search" \
  -H "Content-Type: application/json" \
  -d '{"Q":"Exception","Opts":{"NumContextLines":3,"MaxMatchCount":10}}'
```

能返回 JSON（含 `FileMatches` 等）即表示正常。

## 五、索引更新

仓库 `git pull` 或重新 clone 后，需重新建索引：

```bash
bash scripts/index-zoekt-all.sh
```

然后重启 zoekt-webserver，或等待其自动重载（视版本而定）。

## 六、常见问题

### 报告里出现「未从Zoekt命中结果中读取到本地文件内容」

可能原因：

1. **Zoekt 未部署或未建索引**：确认 Zoekt 已启动，且对该服务的 `local_dir` 建过索引。
2. **路径不一致**：Zoekt 建索引时的目录必须与 `config.yaml` 中 `local_dir` 一致。例如索引用 `/data/repos/order-service`，则 `local_dir` 也必须是该路径。
3. **repo_name 与 service_name 不一致**：建索引时 `-repo_name` 建议与 `service_name` 相同，否则可能被过滤掉。
4. **仓库未同步**：先执行 `POST /repos/sync` 拉取代码。

[English](en/01-zoekt.md)

### Zoekt 返回 0 命中

- 检查查询词是否在代码中存在。
- 检查 Zoekt 索引中 repo 名是否与 `service_name` 一致。
- 确认 zoekt-webserver 已加载索引（重启后需重新加载）。
