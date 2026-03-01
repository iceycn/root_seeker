# Git 仓库源（统一接口）

配置一次平台凭证后，通过**同一套接口**获取仓库、配置到分析工具，不区分底层是 Gitee、GitHub、Codeup 还是 GitLab。

## 一、设计原则

- **统一接口**：配置保存后，所有操作使用同一套 API，不暴露平台差异
- **一次配置**：`PUT /git-source/config` 保存凭证，自动拉取仓库列表
- **配置即用**：`PUT /git-source/repos/{id}` 将仓库加入分析工具，`POST /git-source/sync` 拉取代码

## 二、统一接口（4+1）

| 接口 | 说明 |
|------|------|
| `PUT /git-source/config` | 保存平台凭证，自动拉取仓库列表 |
| `GET /git-source/repos` | 获取仓库列表（?search=, ?enabled_only=） |
| `GET /git-source/repos/{id}` | 获取仓库详情（含分支，?branch_search=） |
| `PUT /git-source/repos/{id}` | 配置仓库到分析工具（启用、选分支） |
| `POST /git-source/sync` | 同步已配置仓库到本地 |

## 三、使用流程

1. **配置**：`PUT /git-source/config` 传入 `domain`、`username`、`password`（平台自动识别或传 `platform`）
2. **选仓库**：`GET /git-source/repos` 查看列表，`GET /git-source/repos/{id}` 查看详情与分支
3. **加入分析**：`PUT /git-source/repos/{id}` 传入 `{enabled: true, branches: ["main"]}`，新增/修改后默认立刻同步
4. **同步**：也可手动 `POST /git-source/sync`，或依赖 periodic 定时同步

## 四、支持的平台（配置时区分，调用时统一）

| 平台 | domain 示例 | username | password |
|------|-------------|----------|----------|
| Gitee | gitee.com | 账号 | 密码或 Token |
| GitHub | github.com | 任意 | Personal Access Token |
| GitLab | gitlab.com | 任意 | Personal Access Token |
| Codeup | openapi-rdc.aliyuncs.com | organizationId | 个人访问令牌 |

## 五、存储配置（config.yaml）

```yaml
git_source:
  enabled: true
  repos_base_dir: "data/repos_from_git"
  storage:
    type: "file"
    file_path: "data/git_source.json"
```

MySQL 存储：`type: "mysql"`，并配置 host、port、user、password、database。各项目维护自己的 config.yaml，不跨项目读取。与 RootSeeker Admin 共用同一库时，两边配置相同 host/port/user/password 即可。

## 六、与分析工具集成

已配置的仓库会参与 periodic 定时同步与向量索引更新，分析错误时可检索其代码。

[← 批量聚类](09-batch-cluster.md) | [返回文档索引](../DOCUMENTATION_INDEX.md)
