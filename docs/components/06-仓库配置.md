# 仓库配置指南

RootSeeker 通过 `repos` 配置将服务名映射到本地代码仓库，用于 Zoekt 检索、向量索引和证据收集。

## 一、配置项说明

在 `config.yaml` 中：

```yaml
repos:
  - service_name: "order-service"
    git_url: "https://git.example.com/org/order-service.git"
    local_dir: "/data/repos/order-service"
    repo_aliases: ["order"]
    language_hints: ["python"]
```

### 字段说明

| 字段 | 必填 | 说明 |
|------|------|------|
| service_name | 是 | 服务名，与日志中的 service 匹配 |
| git_url | 是 | Git 仓库地址 |
| local_dir | 是 | 本地克隆路径，需与 Zoekt 索引路径一致 |
| repo_aliases | 否 | 别名，用于匹配（如 order 匹配 order-service） |
| language_hints | 否 | 语言提示，如 python、java |

## 二、仓库初始化流程

### 1. 配置 repos

在 `config.yaml` 中为每个服务添加一条 repo 配置。

### 2. 同步仓库（clone/pull）

```bash
# 同步所有仓库
curl -X POST "http://127.0.0.1:8000/repos/sync"

# 只同步指定服务
curl -X POST "http://127.0.0.1:8000/repos/sync?service_name=order-service"
```

应用会并发执行 `git clone` 或 `git pull`，将代码拉到 `local_dir`。

### 3. Zoekt 索引

```bash
bash scripts/index-zoekt-all.sh
```

然后启动 zoekt-webserver。详见 [01-zoekt.md](01-zoekt.md)。

### 4. 向量索引

```bash
# 单个
curl -X POST "http://127.0.0.1:8000/index/repo/order-service"

# 全部
python3 scripts/index-all-repos.py
```

详见 [02-qdrant.md](02-qdrant.md)。

### 5. 依赖图（可选）

```bash
curl -X POST "http://127.0.0.1:8000/graph/rebuild"
```

根据代码中的 HTTP 调用等生成上下游依赖图，供报告「关联服务」使用。

## 三、service_name 匹配规则

- 日志中的 `service_name` 可能为 K8s pod 名，如 `bs-integration-7d8f9c-x2k3m`
- 应用会归一化为 `bs-integration`，再与 `repos[].service_name` 或 `repo_aliases` 匹配
- 建议 `service_name` 与 Zoekt 的 `-repo_name` 一致

## 四、路径一致性

**重要**：`local_dir` 必须在以下场景中保持一致：

1. `config.yaml` 中的 `repos[].local_dir`
2. Zoekt 建索引时的目录（`zoekt-index` 的最后一个参数）
3. 应用运行时的实际路径（相对路径以项目根为基准时需注意）

否则会出现「Zoekt 有命中但读不到文件」的问题。

[English](en/06-repos.md)
