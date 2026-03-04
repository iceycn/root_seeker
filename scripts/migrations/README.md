# 数据库迁移

## analysis_status 表

用于 RootSeeker 分析任务状态同步到数据库，便于 Admin 或其他系统查询。

**状态映射**：
| 内部状态 | 数据库 status | status_display |
|----------|---------------|----------------|
| pending  | pending       | 待调度         |
| running  | parsing       | 解析中         |
| completed| parsed        | 解析完成       |
| failed   | failed        | 解析失败       |

**解析失败**时，`error` 字段记录失败原因。

**002 迁移**：新增 `repo_id` 列，关联 `git_source_repos.id`，实现日志与仓库关联。若列已存在，可跳过 ADD COLUMN 语句。

**004 迁移**：repo_index_status 单字段状态。将 qdrant_indexed/qdrant_indexing、zoekt_indexed/zoekt_indexing 合并为 qdrant_status、zoekt_status（值：未索引|索引中|已索引|清理中）。

## 执行迁移

```bash
# 从 config.yaml 读取 config_db 并执行
python3 scripts/run-migration.py

# 仅打印 SQL，不执行
python3 scripts/run-migration.py --dry-run

# 使用环境变量覆盖连接信息
MYSQL_HOST=localhost MYSQL_PORT=3306 MYSQL_USER=root MYSQL_PASSWORD=xxx MYSQL_DATABASE=root_seeker python3 scripts/run-migration.py
```

确保 `config.yaml` 中 `config_db` 已正确配置（host、port、user、password、database）。
