# Zoekt 傻瓜部署

Zoekt 用于代码词法/符号/正则检索，RootSeeker 通过 HTTP 调用其 `/api/search` 接口。

> **安装指南**：若需从零安装 Zoekt，见 [依赖组件安装指南](../安装依赖.md#三zoekt-安装)。

## 1. 适用环境

- 内网 Linux 服务器（或 macOS 开发机）
- 需先准备好本地 Git 仓库目录（与 `config.yaml` 中 `repos[].local_dir` 一致）

## 2. 安装方式一：Go 安装（推荐内网自建）

```bash
# 需要 Go 1.19+
# 使用 google/zoekt（API 兼容）
go install github.com/google/zoekt/cmd/zoekt-index@latest
go install github.com/google/zoekt/cmd/zoekt-webserver@latest
```

安装后得到：

- `zoekt-index`：对指定目录建索引
- `zoekt-webserver`：提供 HTTP 搜索服务（默认端口 6070）

## 3. 建索引

为每个服务的本地仓库建索引，索引输出到同一索引目录（例如 `/data/zoekt/index`）：

```bash
export ZOOKT_INDEX_DIR=/data/zoekt/index
mkdir -p "$ZOOKT_INDEX_DIR"

# 示例：为 order-service 建索引
zoekt-index \
  -index "$ZOOKT_INDEX_DIR" \
  -repo_name "order-service" \
  /data/repos/order-service
```

- `-repo_name`：仓库在 Zoekt 中的名称，建议与 `config.yaml` 里 `service_name` 一致，便于后续按 repo 过滤（若实现）。
- 多仓库：对每个 `local_dir` 执行一次，均写入同一 `-index` 目录。

## 4. 启动搜索服务

```bash
zoekt-webserver \
  -index "$ZOOKT_INDEX_DIR" \
  -listen ":6070"
```

- 默认监听 `:6070`，与 `config.example.yaml` 中 `zoekt.api_base_url: "http://127.0.0.1:6070"` 一致。
- 若部署在其他机器，将 `api_base_url` 改为 `http://<zoekt 主机>:6070`。

## 5. 验证

```bash
curl -s -X POST "http://127.0.0.1:6070/api/search" \
  -H "Content-Type: application/json" \
  -d '{"Q":"Exception","Opts":{"NumContextLines":3,"MaxMatchCount":10}}'
```

能返回 JSON（含 FileMatches 等）即表示正常。

## 6. 与 RootSeeker 的对应

- 在 `config.yaml` 中配置：

```yaml
zoekt:
  api_base_url: "http://<Zoekt 主机>:6070"
```

- 应用内通过 `ZoektClient` 调用 `POST .../api/search`，传 `Q`（查询串）与 `Opts`。
- 若多仓库共用一个 Zoekt 实例，当前实现未按 repo 过滤，检索结果为全索引；后续可在 `ZoektClient.search` 中增加 `RepoIDs` 或按名称过滤（见 [优化清单.md](../优化清单.md)）。

## 7. 索引更新（仓库更新后）

仓库 `git pull` 或重新 clone 后，需重新对该目录执行 `zoekt-index`，再重启或等待 zoekt-webserver 自动重载索引（视版本而定）。可写定时任务或与 `POST /repos/sync` 联动脚本。

## 8. 报告里出现「未从Zoekt命中结果中读取到本地文件内容」

该提示表示 Zoekt 有命中，但应用无法在本地 `repo_local_dir` 下读到对应文件，常见原因：

1. **Zoekt 未部署或未建索引**：未配置 Zoekt 或未对当前服务的 `local_dir` 建索引，则无命中；若 Zoekt 返回的是其他仓库的命中，会被过滤，也可能导致无可用证据。
2. **路径不一致**：Zoekt 建索引时用的目录（如 `/data/repos/enterprise-manage-api`）与 `config.yaml` 里该服务的 `local_dir`（如 `/Users/beisen/IdeaProjects/enterprise-manage-api`）不同。应用会按 `local_dir` 读文件，索引里的路径需与本地目录结构一致（文件名相对仓库根一致）。建索引时建议 `-repo_name` 与 `service_name` 一致，应用会按 repo 过滤并自动去掉 `file_path` 前的 repo 前缀。
3. **仓库未镜像到本地**：`local_dir` 指向的目录不存在或未执行 `POST /repos/sync` 拉取代码。

处理建议：确认 Zoekt 已对该服务的 `local_dir` 建索引、`local_dir` 存在且与索引路径结构一致；或暂时不依赖 Zoekt 证据（仍可有 Qdrant 向量证据与构建配置证据）。

## 8. Docker 方式（可选）

若使用 Sourcegraph 提供的 Zoekt 镜像或自建镜像，需保证：

- 容器内提供 HTTP 接口，路径为 `/api/search`，请求体含 `Q`、`Opts`（及可选 `RepoIDs`）。
- 将索引目录挂载为持久化卷，并先在本机或其它容器内用 `zoekt-index` 生成索引，再启动 webserver 容器。

具体镜像与启动命令可参考 [google/zoekt](https://github.com/google/zoekt) 或公司内已有 Zoekt 部署规范。
