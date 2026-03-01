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
