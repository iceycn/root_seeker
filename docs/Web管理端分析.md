# WebAdmin 界面方案分析

## 一、需求概述

- **触发条件**：git_source 使用 MySQL 存储时，启用 WebAdmin
- **核心功能**：仓库管理（列表、启用/禁用、分支选择、同步）
- **鉴权**：账号密码登录（区别于现有 API Key）
- **集成方式**：与现有 FastAPI 应用深度集成，复用 GitSourceService
- **界面要求**：友好、现成开发脚手架

---

## 二、现成脚手架方案对比（友好 UI）

| 方案 | UI 框架 | 脚手架 | 登录 | 与 MySQL 契合度 | 推荐度 |
|------|---------|--------|------|-----------------|--------|
| **FastAPI-Amis-Admin** | Amis（百度低代码） | `faa new` CLI | ✅ 内置 + FastAPI-User-Auth | SQLModel/SQLAlchemy | ⭐⭐⭐⭐⭐ |
| **SQLAdmin** | Tabler（成熟后台 UI） | 直接集成 | ✅ 自定义 AuthenticationBackend | SQLAlchemy | ⭐⭐⭐⭐ |
| **FastAPI Admin** | Tabler | Docker 模板 | ✅ 内置 | Tortoise ORM（不兼容） | ⭐⭐ |
| **自建 Jinja2** | 需自选 CSS | 无 | 自实现 | 直接复用现有逻辑 | ⭐⭐ |

---

## 三、首选推荐：FastAPI-Amis-Admin

### 3.1 选择理由

1. **现成脚手架**：`pip install fastapi_amis_admin[cli]` 后可用 `faa new project_name --init` 快速初始化
2. **友好 UI**：基于 [Amis](https://baidu.gitee.io/amis)，低代码、表单/表格自动生成，界面现代
3. **内置登录**：AdminSite 自带登录页，可配合 [FastAPI-User-Auth](https://github.com/amisadmin/fastapi_user_auth) 做 RBAC
4. **与 MySQL 契合**：支持 SQLModel、SQLAlchemy，可映射现有 `git_source_repos` 表
5. **中文文档**：文档完善，社区活跃

### 3.2 在线演示与文档

- 官方 Demo：<http://demo.amis.work/admin>
- 文档：<http://docs.amis.work/zh/>

### 3.3 快速开始

```bash
# 安装（含 CLI 脚手架）
pip install fastapi_amis_admin[cli] fastapi_amis_admin[sqlmodel]

# 初始化项目（可选，用于参考结构）
faa new webadmin_demo --init
faa run
```

### 3.4 集成到 RootSeeker 的思路

1. **条件挂载**：仅当 `git_source.storage.type == "mysql"` 且 `webadmin.enabled == true` 时挂载
2. **数据库**：复用 git_source 的 MySQL 连接，创建 SQLAlchemy/SQLModel 模型映射 `git_source_repos`、`git_source_credential`
3. **登录**：使用配置的 `webadmin.username` / `webadmin.password`，或单独建 `admin_users` 表
4. **仓库管理**：通过 ModelAdmin 自动 CRUD，或 FormAdmin 自定义表单调用 `GitSourceService`
5. **同步按钮**：在 PageAdmin 中嵌入自定义页面，调用 `POST /git-source/sync` 逻辑

### 3.5 依赖

```
fastapi_amis_admin[cli]
fastapi_amis_admin[sqlmodel]  # 或 [sqlalchemy]
sqlalchemy
pymysql
```

---

## 四、备选推荐：SQLAdmin

### 4.1 选择理由

1. **成熟 UI**：基于 [Tabler](https://tabler.io/)，专业后台风格
2. **轻量**：专注 CRUD，无额外低代码层
3. **认证灵活**：`AuthenticationBackend` 可自定义账号密码校验
4. **在线 Demo**：<https://sqladmin-demo.aminalaee.dev/admin/>

### 4.2 集成思路

1. 引入 SQLAlchemy，定义 `GitSourceRepo`、`GitSourceCredential` 模型映射现有表
2. 自定义 `AuthenticationBackend`：校验 config 中的 `webadmin_username` / `webadmin_password`
3. 挂载到 `/admin`，仅 MySQL 模式启用

### 4.3 依赖

```
sqladmin[full]
sqlalchemy
pymysql
```

### 4.4 启用条件（两种方案通用）

```yaml
# config.yaml
git_source:
  enabled: true
  storage:
    type: mysql
    host: localhost
    database: root_seeker
    # ...
  webadmin:
    enabled: true
    username: admin
    password: "从环境变量 ROOT_SEEKER_WEBADMIN_PASSWORD 读取，或此处配置"
```

- 仅当 `git_source.storage.type == "mysql"` 且 `webadmin.enabled == true` 时挂载 WebAdmin

---

## 五、与现有系统集成方式

### 5.1 路由挂载

```python
# app.py
if git_source_service and _is_mysql_storage(cfg) and cfg.webadmin_enabled:
    from root_seeker.webadmin import create_webadmin_router
    app.mount("/webadmin", create_webadmin_router(git_source_service, ...))
```

### 5.2 鉴权分离

| 入口 | 鉴权方式 |
|------|----------|
| REST API `/git-source/*` | `X-Api-Key` (require_api_key) |
| WebAdmin `/webadmin/*` | Session（账号密码登录） |

两者互不干扰，WebAdmin 登录后通过 Session 访问，不依赖 API Key。

### 5.3 数据流

```
WebAdmin (Jinja2)  →  GitSourceService  →  MySQLStorageBackend
       ↑                      ↑
   Session 登录          与 REST API 共用
```

---

## 六、建议实施步骤（以 FastAPI-Amis-Admin 为例）

1. **Phase 1**：在 `config` 中增加 `webadmin` 配置项，条件判断 `storage.type == "mysql"`
2. **Phase 2**：安装 `fastapi_amis_admin[cli,sqlmodel]`，用 `faa new` 生成参考项目，熟悉结构
3. **Phase 3**：定义 SQLAlchemy/SQLModel 模型映射 `git_source_repos`、`git_source_credential`
4. **Phase 4**：创建 AdminSite，挂载到 `/admin`，配置登录（webadmin 账号密码）
5. **Phase 5**：注册 ModelAdmin 管理仓库，或 FormAdmin 自定义同步等操作
6. **Phase 6**（可选）：与 `MySQLStorageBackend` 统一为 SQLAlchemy 读写，或保持双写协调

---

## 七、小结

| 需求 | 推荐方案 |
|------|----------|
| 友好界面 + 现成脚手架 | **FastAPI-Amis-Admin**（Amis UI + `faa new` CLI） |
| 轻量、Tabler 风格 | **SQLAdmin** |
| **新开项目 + 异构架构** | **若依（RuoYi）**——独立 Java 项目，共享 MySQL，见 [Web管理端若依架构.md](./Web管理端若依架构.md) |
| 零 ORM、最小依赖 | 自建 Jinja2（不推荐，界面需自搭） |

---

*文档更新时间：2025-02-03*
