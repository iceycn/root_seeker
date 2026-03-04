# 仓库同步与索引逻辑分析

## 一、当前状态总览

| 能力 | 状态 | 说明 |
|------|------|------|
| Git 下载集成 | ✅ 已集成 | git_source + periodic_tasks + POST /git-source/sync |
| 轻量级 fetch 检测 | ✅ 已有 | repo_mirror 先 fetch，再 rev-list 检测是否有更新 |
| 有变更才 pull | ✅ 已有 | 无更新时返回 no_change，不触发索引 |
| 向量增量索引 | ✅ 已实现 | git diff ORIG_HEAD HEAD 获取变更文件，仅索引变更部分 |
| Zoekt 自动更新 | ⚠️ 需手动 | periodic 不触发 Zoekt，需执行 `bash scripts/index-zoekt-all.sh` |
| POST /repos/sync | ✅ 已修复 | 合并 cfg.repos 与 git_source 已启用仓库 |
| POST /graph/rebuild | ✅ 已修复 | 合并 cfg.repos 与 git_source 已启用仓库 |
| 全量重载 | ✅ 已实现 | POST /repos/full-reload、POST /index/reset-all、POST /index/repo/{name}/reset |
| 按仓库排队加载 | ✅ 已实现 | auto_index_concurrency=1，索引时一次只处理一个仓库 |

## 二、流程梳理

### 2.1 仓库来源

- **config.repos**：config.yaml 中静态配置
- **git_source**：从 Gitee/GitHub 等平台拉取列表，用户启用后加入 catalog

### 2.2 同步流程（repo_mirror）

1. `git fetch --all --prune`（轻量，只拉元数据）
2. `git rev-list --count HEAD..@{upstream}` 检测是否有新提交
3. `git pull --ff-only` 拉取（pull 后 ORIG_HEAD 指向旧 HEAD，供增量索引使用）
4. 返回 status：`updated` | `cloned` | `no_change` | `error`

### 2.3 定时任务（periodic_tasks）

- 使用 `repos_for_sync` = cfg.repos + git_source 已启用仓库 ✅
- 同步后仅对 `updated` / `cloned` 的仓库触发向量索引 ✅
- **updated**：尝试增量索引（git diff ORIG_HEAD HEAD），失败则回退全量
- **cloned**：全量索引（新克隆无 ORIG_HEAD）
- Zoekt：需手动执行 `bash scripts/index-zoekt-all.sh` 或定时任务

### 2.4 全量重载与排队机制（事件化）

- **POST /index/reset-all**：发出 RequestResetAllEvent，清除全部向量；`reindex=true` 时为每个仓库入队索引
- **POST /index/repo/{service_name}/resync**：发出 RequestResyncRepoEvent，先清除后添加，添加完成后触发依赖图重建（通过队列）
- **POST /index/repo/{service_name}/reset**：清除单仓库向量并全量重索引（同步执行，保留兼容）
- **POST /repos/full-reload**：发出 RequestFullReloadEvent，后台同步后为每个仓库入队移除与索引
- **事件流程**：详见 [EVENT_FLOW.md](EVENT_FLOW.md)

### 2.5 向量增量索引（vector_indexer）

- `index_repo(..., incremental=True)`：`git diff --name-only ORIG_HEAD HEAD` 获取变更的 .py/.java 文件
- 对每个变更文件：先 `delete_points_by_file` 删旧点，再 chunk + embed + upsert
- ORIG_HEAD 不存在或 diff 失败时回退全量索引

### 2.6 索引状态（repo_index_status）

- **单字段状态**：`qdrant_status`、`zoekt_status` 取值：未索引 | 索引中 | 已索引 | 清理中
- **流转**：未索引 → 索引中 → 已索引；已索引 → 清理中 → 未索引
- **乐观更新**：Admin 发起索引/清除时先改本地状态，再调 RootSeeker，回调到达后更新为最终状态
- 详见 [callback-integration.md](callback-integration.md)

## 三、任务列表（无需手动）

| 步骤 | 自动化 | 说明 |
|------|--------|------|
| 1. 仓库同步 | periodic / POST /repos/sync | fetch 检测 → 有变更才 pull |
| 2. 向量索引 | periodic / POST /index/repo/{name} | 有变更时增量，否则跳过或全量 |
| 3. Zoekt 索引 | 手动 | `bash scripts/index-zoekt-all.sh` |
| 4. 依赖图 | POST /graph/rebuild | 含 git_source 仓库 |
