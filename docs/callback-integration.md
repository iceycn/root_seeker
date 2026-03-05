# 索引回调对接说明

RootSeeker 在索引/清除任务完成后，会 POST 到 Admin 配置的回调 URL，更新 `repo_index_status` 表。

## 一、索引状态模型（单字段）

### 1.1 状态值

| 状态 | 说明 |
|------|------|
| 未索引 | 该仓库尚未建立索引 |
| 索引中 | 正在建立索引（乐观更新或 RootSeeker 任务执行中） |
| 已索引 | 索引已完成 |
| 清理中 | 正在清除索引（乐观更新或 RootSeeker 任务执行中） |

### 1.2 状态流转

```
未索引 → 索引中 → 已索引
已索引 → 清理中 → 未索引
```

### 1.3 数据库字段

| 字段 | 类型 | 说明 |
|------|------|------|
| service_name | VARCHAR(255) | 主键，与 git_source full_name.replace("/","-") 一致 |
| qdrant_status | VARCHAR(20) | Qdrant 状态：未索引/索引中/已索引/清理中 |
| qdrant_count | INT | Qdrant 向量点数（已索引时有效） |
| zoekt_status | VARCHAR(20) | Zoekt 状态：未索引/索引中/已索引/清理中 |
| updated_at | DATETIME | 最后更新时间 |

迁移脚本：`scripts/migrations/004_repo_index_status_single_field.sql`

## 二、乐观更新流程

Admin 在发起索引/清除操作时，**先改本地状态，再调 RootSeeker 接口**，回调到达后更新为最终状态。

| 操作 | 先设状态 | 调用接口 | 回调后状态 |
|------|----------|----------|------------|
| 启用仓库 | 索引中 | syncSingleRepo | 已索引（成功）/ 未索引（失败） |
| 禁用仓库 | 清理中 | clearRepoIndex | 未索引 |
| 索引 Qdrant | 索引中 | indexRepo | 已索引 |
| 索引 Zoekt | 索引中 | indexZoektRepo | 已索引 |
| 清除索引 | 清理中 | clearRepoIndex | 未索引 |
| 重新索引 | 索引中 | resetRepoIndex | 已索引 |
| 重新同步 | 索引中 | resyncRepoIndex | 已索引 |

## 三、回调 URL

- 参考模板：`http://<admin_host>:<admin_port>/gitsource/index/callback`
- 本机一键启动默认端口：`8080`
- Docker 全栈默认端口：`8088`
- 配置：`root.seeker.adminCallbackUrl`（sys_config）或 `root-seeker.admin-callback-url`（application.yml）

## 四、Payload 字段对照

| RootSeeker 发送 | Admin 接收 | 说明 |
|-----------------|-------------|------|
| service_name | payload.get("service_name") | 必填，仓库标识 |
| task_type | payload.get("task_type") | qdrant / zoekt / remove_qdrant / remove_zoekt / resync / sync |
| status | payload.get("status") | completed / failed |
| qdrant_indexed | - | qdrant 完成时=1，remove_qdrant 时=0（兼容旧格式） |
| qdrant_count | getInt(payload, "qdrant_count", 0) | 向量块数 |
| zoekt_indexed | - | zoekt 完成时=1，remove_zoekt 时=0（兼容旧格式） |
| qdrant_status | payload.get("qdrant_status") | 可选，sync 时 RootSeeker 直接返回状态字符串 |
| zoekt_status | payload.get("zoekt_status") | 可选，sync 时 RootSeeker 直接返回状态字符串 |

## 五、task_type 与 Admin 处理逻辑

| task_type | status | Admin 行为 |
|-----------|--------|------------|
| qdrant | completed | qdrant_status=已索引, qdrant_count=payload |
| qdrant | failed | 保持原状态 |
| zoekt | completed | zoekt_status=已索引 |
| zoekt | failed | 保持原状态 |
| remove_qdrant | completed | qdrant_status=未索引, qdrant_count=0 |
| remove_zoekt | completed | zoekt_status=未索引 |
| resync | completed | 从 payload 取 qdrant_indexed, qdrant_count, zoekt_indexed 映射为 status |
| sync | completed | 从 payload 取 qdrant_status/zoekt_status，或从 qdrant_indexed 等推导 |

## 六、service_name 匹配规则

- **写入**：callback 的 service_name 直接作为 `repo_index_status.service_name` 存储
- **读取**：`getIndexStatus` 遍历 `git_source_repos`，对每个 repo 计算 `sn = fullName.replace("/", "-")` 或 `fullPath.replace("/", "-")`
- **匹配**：`statusMap.get(sn)`，若为空则尝试 `sn.replace("_", "-")` 和 `sn.replace("-", "_")`，以兼容 `api-distribution` 与 `api_distribution` 等格式差异

## 七、RootSeeker 各事件 payload 示例

```json
// Qdrant 索引完成
{"service_name": "api-distribution", "task_type": "qdrant", "status": "completed", "qdrant_indexed": 1, "qdrant_count": 100}

// Zoekt 索引完成
{"service_name": "api-distribution", "task_type": "zoekt", "status": "completed", "zoekt_indexed": 1}

// Qdrant 移除完成
{"service_name": "api-distribution", "task_type": "remove_qdrant", "status": "completed", "qdrant_indexed": 0}

// Zoekt 移除完成
{"service_name": "api-distribution", "task_type": "remove_zoekt", "status": "completed", "zoekt_indexed": 0}
```

## 八、RootSeeker GET /index/status 返回格式（sync 用）

Admin 调用「重新同步索引状态」时，从 RootSeeker 拉取实时状态并写入 `repo_index_status`。RootSeeker 返回：

```json
{
  "repos": [
    {
      "service_name": "api-distribution",
      "qdrant_status": "已索引",
      "qdrant_count": 103,
      "zoekt_status": "已索引",
      "qdrant_indexed": true,
      "qdrant_indexing": false,
      "qdrant_removing": false,
      "zoekt_indexed": true,
      "zoekt_indexing": false,
      "zoekt_removing": false
    }
  ]
}
```

- `qdrant_status` / `zoekt_status`：单字段状态，优先使用
- `qdrant_removing` / `zoekt_removing`：清除任务执行中时为 true
- 旧字段 `qdrant_indexed` 等保留兼容，sync 时用于推导 status

## 九、并发与竞态

`remove_qdrant` 与 `remove_zoekt` 回调可能几乎同时到达。Admin 使用 `updateQdrantFromCallback`、`updateZoektFromCallback` 做**局部更新**，仅修改各自相关字段，避免互相覆盖导致状态错误。

## 十、常见问题

1. **adminCallbackUrl 未配置**：若 `sys_config` 中无 `root.seeker.adminCallbackUrl`，RootSeeker 不会传 `callback_url`，回调不会发送。执行 `scripts/add-admin-callback-url.sql` 或在前端「RootSeeker 配置」填写回调地址。
2. **记录不存在时 UPDATE 无效**：`repo_index_status` 中无对应 `service_name` 时，纯 `UPDATE` 会更新 0 行。Admin 已修复：当记录不存在时使用 `insertOrUpdate` 插入新记录。
3. **状态不刷新**：Admin 列表页每 15 秒轮询 `getIndexStatus`。也可手动点击「重新同步索引状态」从 RootSeeker 拉取实时状态。
