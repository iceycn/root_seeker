# RootSeeker Admin + MySQL 部署（本机 / Docker）

本页面向“需要使用管理端（若依）”的场景：仓库管理、索引触发、配置管理、回调链路等。

## 1. 两种部署方式

| 方式 | 适用场景 | 端口 | MySQL |
|------|----------|------|------|
| Docker 全栈（推荐） | 想快速跑通全套能力 | Admin 8088 | 容器内置并自动初始化 |
| 本机运行 Admin | 已有 MySQL，或需要接公司内网库 | Admin 8080 | 自备并手动初始化 |

端口总览见 [PORTS_AND_ENDPOINTS.md](../PORTS_AND_ENDPOINTS.md)。

## 2. Docker 全栈（开箱即用）

参考 [root_seeker_docker/README.md](../../root_seeker_docker/README.md)：

- 一键启动：`bash root_seeker_docker/start.sh`
- 宿主机访问：RootSeeker `8000`，Admin `8088`，MySQL `3307`
- 首次启动：会自动执行 `mysql-init/sql/` 下 SQL，初始化若依表与 Demo 配置

## 3. 本机运行 Admin（需要自备 MySQL）

### 3.1 初始化数据库与表

按 Admin 项目文档操作：见 [README_ROOTSEEKER.md](../../ruoyi-rootseeker-admin/README_ROOTSEEKER.md)。

### 3.2 启动方式

方式一：项目根目录一键启动（推荐）

- `bash scripts/start-all-one-click.sh`
- 默认端口：RootSeeker `8000`，Admin `8080`

方式二：仅启动 Admin

- `cd ruoyi-rootseeker-admin && mvn spring-boot:run -pl ruoyi-admin`

### 3.3 MySQL 连接配置（环境变量覆盖）

Admin 默认使用 `localhost:3306/root_seeker`，可通过环境变量覆盖：

- `MYSQL_HOST`
- `MYSQL_PORT`
- `MYSQL_USERNAME`
- `MYSQL_PASSWORD`
- `MYSQL_DATABASE`

示例（仅示意，不建议把密码写进仓库文件）：

- `MYSQL_HOST=<host> MYSQL_PORT=<port> MYSQL_USERNAME=<user> MYSQL_PASSWORD=<password> mvn spring-boot:run -pl ruoyi-admin`

## 4. Admin 与 RootSeeker 的对接配置

### 4.1 RootSeeker 地址

推荐在 Admin 的 `sys_config` 中配置：

- `root.seeker.baseUrl`（默认 `http://localhost:8000`）

说明见 [README_ROOTSEEKER.md](../../ruoyi-rootseeker-admin/README_ROOTSEEKER.md)。

### 4.2 回调地址

RootSeeker 索引完成后回调 Admin：

- `http://<admin_host>:<admin_port>/gitsource/index/callback`

对接协议见 [callback-integration.md](../callback-integration.md)。
