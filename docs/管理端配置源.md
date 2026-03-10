# Admin 配置来源全览

## 一、数据源配置（MySQL）

### 1. 主配置源（生效）

| 文件 | 路径 | 说明 |
|------|------|------|
| **application-druid.yml** | `ruoyi-rootseeker-admin/ruoyi-admin/src/main/resources/application-druid.yml` | 唯一数据源配置，通过 `${MYSQL_HOST}` 等环境变量占位 |

```yaml
url: jdbc:mysql://${MYSQL_HOST:localhost}:${MYSQL_PORT:3306}/${MYSQL_DATABASE:root_seeker}?useUnicode=...&useSSL=false&...
```

- **默认值**：localhost:3306，useSSL=false
- **覆盖方式**：环境变量 `MYSQL_HOST`、`MYSQL_PORT`、`MYSQL_USERNAME`、`MYSQL_PASSWORD`、`MYSQL_DATABASE`

### 2. 环境变量来源

| 来源 | 文件/方式 | 说明 |
|------|-----------|------|
| **.env** | 项目根目录 `.env`（gitignore） | 启动脚本 `source .env` 后 export |
| **.env.example** | 项目根目录 | 模板，含 MYSQL_HOST=47.100.101.21, MYSQL_PORT=53266 |
| **start-all-one-click.sh** | scripts/ | 加载 .env，export MYSQL_*，用 `env MYSQL_*=... mvn` 传参 |
| **restart-all.sh** | scripts/ | 同上 |
| **restart-all-one-click.sh** | scripts/ | 调用 stop + start-all-one-click |

### 3. 其他脚本中的 MYSQL_* 引用（不直接影响 Admin 启动）

| 脚本 | 用途 |
|------|------|
| scripts/exec-sql.sh | 执行 SQL，用 MYSQL_* 连接 |
| scripts/check-sys-config-55432.sh | 查询 sys_config |
| scripts/check-repo-status.sh | 查询仓库状态 |
| scripts/run-admin.sh | 单独启动 Admin |
| scripts/run-migration.py | Python 迁移脚本 |
| scripts/create_analysis_status_table.py | Python 建表 |

### 4. Docker 环境（与本地 Admin 无关）

| 文件 | 说明 |
|------|------|
| root_seeker_docker/docker-compose.yml | Admin 容器内 MYSQL_HOST=mysql, MYSQL_PORT=3306 |

---

## 二、非数据源配置（Admin 不读取）

| 文件 | 说明 |
|------|------|
| **config.yaml** | Python RootSeeker 配置，Admin 不读 |
| **config.example.yaml** | 同上，含 config_db（Python 用） |
| **root_seeker_docker/config.docker.yaml** | 容器内 RootSeeker 配置 |

---

## 三、sys_config 表（业务配置，非数据源）

- 存储：root.seeker.baseUrl、root.seeker.adminCallbackUrl、sys.index.skinName 等
- **不存储**：spring.datasource、jdbc url
- 需连接 MySQL 后才能读取，不能用于数据源配置

---

## 四、项目内 55432 / useSSL 出现位置

| 位置 | 说明 |
|------|------|
| **scripts/fix-mysql-port-55432-to-53266.sql** | 修复脚本，用于替换 sys_config 中的 55432 |
| **scripts/check-sys-config-55432.sh** | 查询脚本 |
| **docs/WEBADMIN_RUOYI_ARCHITECTURE.md** | 文档示例，含 useSSL=true（仅文档，不加载） |

**结论**：项目内**没有**任何地方将 55432 或 useSSL=true 写入 Admin 数据源配置。

---

## 五、55432 / useSSL=true 的来源（已定位）

**根因**：`env MYSQL_HOST=... mvn ...` 会**继承父进程环境变量**。若存在 `SPRING_DATASOURCE_DRUID_MASTER_URL`，会**完全覆盖** application-druid.yml 中的 url（包括 useSSL、端口等）。

**证据**：日志中的 url 为 `useSSL=true`、无 `allowPublicKeyRetrieval`，与 application-druid.yml（`useSSL=false`、`allowPublicKeyRetrieval=true`）不一致，说明来自外部覆盖。

**修复**：启动脚本已改为 `env -u SPRING_DATASOURCE_DRUID_MASTER_URL -u SPRING_DATASOURCE_DRUID_SLAVE_URL -u SPRING_DATASOURCE_URL MYSQL_HOST=... mvn ...`，显式清除可能覆盖数据源的 Spring 环境变量。

**其他可能来源**（若仍出现异常）：
1. **IDE Run Configuration**：PyCharm/IntelliJ 中配置的 env 或 JVM 参数
2. **~/.bashrc / ~/.zshrc**：export MYSQL_PORT=55432 或 SPRING_DATASOURCE_*
3. **其他进程**：同一 log 文件被多个进程写入，混入旧日志

---

## 六、配置加载顺序（Spring Boot）

1. 命令行参数 `--spring.datasource...`
2. 系统属性 `-Dspring.datasource...`
3. 环境变量 `SPRING_DATASOURCE_DRUID_MASTER_URL`（优先级高于 yml）
4. `file:./config/application-druid.yml`（若存在）
5. `file:./application-druid.yml`（若存在）
6. `classpath:application-druid.yml`（当前唯一生效的 yml）

**环境变量会覆盖 yml 中的占位符**。若存在 `SPRING_DATASOURCE_DRUID_MASTER_URL` 或 `MYSQL_PORT=55432`，会覆盖 application-druid.yml。
