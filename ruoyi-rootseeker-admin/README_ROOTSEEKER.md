# RootSeeker 管理端

RootSeeker 管理端与 RootSeeker 分析服务异构集成，用于管理 Git 仓库（与 Python RootSeeker 共享 MySQL）。

## 项目位置

位于 `root_seek` 目录下，与 `root_seeker` 平级：`root_seek/ruoyi-rootseeker-admin/`。

## 数据库初始化

1. 创建数据库：
```sql
CREATE DATABASE root_seeker DEFAULT CHARACTER SET utf8mb4;
```

2. 导入系统表（在 root_seeker 库执行）：
```bash
mysql -u root -p root_seeker < sql/ry_20250416.sql
```

3. 导入 Git 仓库表与菜单：
```bash
mysql -u root -p root_seeker < sql/git_source.sql
mysql -u root -p root_seeker < sql/git_source_menu.sql
```

4. **已有表升级**：若 `git_source_repos` 表为旧版创建（报错 `Unknown column 'full_path'`），执行：
```bash
# 使用与 application-druid.yml 中相同的 host/port/user
mysql -h <host> -P <port> -u <user> -p root_seeker < sql/git_source_repos_add_columns.sql
```

## 配置

1. **数据库**：各项目维护自己的配置。管理端在 `ruoyi-admin/src/main/resources/application-druid.yml` 中配置 MySQL，默认 localhost:3306/root_seeker。
   - 可通过环境变量覆盖：`MYSQL_HOST`、`MYSQL_PORT`、`MYSQL_USERNAME`、`MYSQL_PASSWORD`、`MYSQL_DATABASE`
   - 示例：`MYSQL_HOST=192.168.1.100 MYSQL_PORT=3306 MYSQL_USERNAME=root MYSQL_PASSWORD=xxx mvn spring-boot:run -pl ruoyi-admin`

2. **RootSeeker 服务地址**（二选一，推荐方式一）：
   - **方式一（推荐）**：在管理端「系统管理 → 参数设置」中配置 `root.seeker.baseUrl`，默认值 `http://localhost:8000`。导入 `sql/git_source.sql` 时会自动插入该配置项。
   - **方式二**：在 `application.yml` 中配置：
   ```yaml
   root-seeker:
     base-url: http://localhost:8000   # RootSeeker 服务地址（sys_config 未配置时生效）
     api-key: your-api-key            # 或环境变量 ROOT_SEEKER_API_KEY
   ```
   优先级：**sys_config 表配置 > application.yml**。

3. **端口**：默认 `8080`（一键启动脚本也默认使用 8080）。可通过以下方式修改：
   - `application.yml` 的 `server.port`
   - 启动参数或环境变量（例如 `SERVER_PORT=8080`、`--server.port=8080`）
   - Docker 全栈部署默认对外暴露 `8088`（见 `root_seeker_docker/README.md`）

## 启动

**方式一（推荐）**：在 root_seek 根目录一键启动全部服务（含 RootSeeker、Admin、Qdrant、Zoekt）：

```bash
cd root_seek
bash scripts/start-all-one-click.sh   # 启动
bash scripts/stop-all-one-click.sh   # 停止
```

**方式二**：仅启动管理端：

```bash
cd ruoyi-rootseeker-admin   # 在 root_seek 根目录下执行
mvn spring-boot:run -pl ruoyi-admin
# 或指定 MySQL：MYSQL_HOST=xxx MYSQL_PORT=3306 MYSQL_USERNAME=root MYSQL_PASSWORD=xxx mvn spring-boot:run -pl ruoyi-admin
```

或运行 `RuoYiApplication` 主类。

**运行目录**：工作目录为 `ruoyi-rootseeker-admin` 项目根目录，日志、上传文件等均在此下：
- 日志：`./logs/`
- 上传：`./uploadPath/`

## 默认账号

- 用户名：`admin`
- 密码：`admin123`

## 功能说明

- **仓库管理**：查看、编辑仓库（启用/禁用、分支选择）
- **拉取仓库列表**：配置凭证后，调用 RootSeeker 拉取 Git 平台仓库
- **同步仓库**：调用 RootSeeker 执行 git clone/pull
- **凭证配置**：保存 Gitee/GitHub/GitLab/Codeup 平台凭证

## 与 RootSeeker 的协作

- 管理端直接读写 `git_source_credential`、`git_source_repos` 表
- 拉取列表、同步操作通过 HTTP 调用 RootSeeker 的 `/git-source/*` 接口
- 需确保 RootSeeker 已启动且 `config.yaml` 中 `git_source.storage.type` 为 `mysql`

## RootSeeker 地址配置说明

| 配置方式 | 位置 | 说明 |
|---------|------|------|
| **RootSeeker 配置页（推荐）** | Git 仓库 → RootSeeker 配置 | 专用配置页面，填写服务地址后保存即可，无需重启 |
| 参数设置 | 系统管理 → 参数设置 → 参数键名 `root.seeker.baseUrl` | 与上同源，修改任一即可 |
| application.yml | `root-seeker.base-url` | 当 sys_config 中未配置时作为兜底 |

**首次使用**：执行 `sql/git_source.sql` 后，`root.seeker.baseUrl` 会自动插入 sys_config，默认 `http://localhost:8000`。在「Git 仓库 → RootSeeker 配置」页面可修改为实际部署地址（如 `http://192.168.1.100:8000`）。

**已有环境**：若未看到「RootSeeker 配置」菜单，执行 `sql/git_source_menu_config.sql` 进行菜单升级。
