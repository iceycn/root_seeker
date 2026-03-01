# 若依（RuoYi）异构架构方案

## 一、方案概述

采用**新开独立项目 + 异构架构**：若依作为管理端，与 RootSeeker（Python）共享 MySQL 数据库，通过表读写 + HTTP 调用完成仓库管理。

| 组件 | 技术栈 | 职责 |
|------|--------|------|
| **RootSeeker** | Python / FastAPI | 核心分析服务，读写 `git_source_*` 表，执行 Git 平台 API、clone/sync |
| **RuoYi-WebAdmin** | Java / Spring Boot + Vue + Element | 管理端 UI，CRUD 仓库与凭证，调用 RootSeeker 接口完成「拉取列表」「同步」 |

---

## 二、架构图

```
┌─────────────────────────────────────────────────────────────────┐
│                         MySQL (共享)                              │
│  git_source_credential | git_source_repos | sys_* (若依系统表)     │
└───────────────┬─────────────────────────────┬───────────────────┘
                │                             │
                │ 读写                         │ 读写
                ▼                             ▼
┌───────────────────────────┐     ┌───────────────────────────┐
│   RootSeeker (Python)     │     │  RuoYi-WebAdmin (Java)     │
│   - GitSourceService      │     │  - 仓库 CRUD                │
│   - 拉取平台仓库列表        │◄────│  - 凭证配置                 │
│   - Git clone/sync        │ HTTP │  - 调用 RootSeeker API     │
│   - 分析、索引、通知        │     │  - 若依权限/菜单            │
└───────────────────────────┘     └───────────────────────────┘
```

---

## 三、数据流与职责划分

### 3.1 共享表结构（RootSeeker 已定义）

**git_source_credential**
| 字段 | 类型 | 说明 |
|------|------|------|
| id | INT | 主键，固定 1 |
| domain | VARCHAR(255) | 平台域名 |
| username | VARCHAR(255) | 账号 |
| password | VARCHAR(512) | 密码/Token |
| platform | VARCHAR(64) | gitee/github/gitlab/codeup |
| created_at | DATETIME | |
| updated_at | DATETIME | |

**git_source_repos**
| 字段 | 类型 | 说明 |
|------|------|------|
| id | VARCHAR(128) | 主键 |
| full_name | VARCHAR(255) | owner/repo |
| git_url | VARCHAR(512) | clone URL |
| default_branch | VARCHAR(128) | 默认分支 |
| description | TEXT | 描述 |
| selected_branches | JSON | 选中的分支列表 |
| enabled | TINYINT(1) | 是否启用 |
| local_dir | VARCHAR(512) | 本地目录 |
| last_sync_at | DATETIME | 最后同步时间 |
| created_at | DATETIME | |
| extra | JSON | 扩展字段 |

### 3.2 职责划分

| 操作 | 执行方 | 实现方式 |
|------|--------|----------|
| 凭证配置（domain/username/password） | RuoYi | 直接写 `git_source_credential` |
| 拉取仓库列表 | RootSeeker | RuoYi 调用 `PUT /git-source/config`，RootSeeker 调 Git 平台 API 并写 `git_source_repos` |
| 仓库启用/禁用、分支选择 | RuoYi | 直接更新 `git_source_repos` |
| 同步到本地（git clone/pull） | RootSeeker | RuoYi 调用 `POST /git-source/sync` |
| 获取分支列表 | RootSeeker | RuoYi 调用 `GET /git-source/repos/{id}?branch_search=xxx` |

---

## 四、若依项目搭建

### 4.1 推荐版本

- **RuoYi-Vue**：前后端分离，Spring Boot + Vue + Element UI，结构清晰
- 仓库：<https://gitee.com/y_project/RuoYi-Vue>

### 4.2 数据库配置

在若依的 `application-druid.yml` 中配置与 RootSeeker **相同的 MySQL**：

```yaml
spring:
  datasource:
    url: jdbc:mysql://localhost:3306/root_seeker?useUnicode=true&characterEncoding=utf8&zeroDateTimeBehavior=convertToNull&useSSL=true&serverTimezone=GMT%2B8
    username: root
    password: xxx
```

- 若依系统表（sys_user、sys_role 等）与 `git_source_*` 表共存于同一库
- 或使用多数据源：默认库为若依业务库，单独配置 `root_seeker` 数据源仅访问 `git_source_*`

### 4.3 代码生成

使用若依「代码生成」功能，基于 `git_source_repos`、`git_source_credential` 表生成：

- Entity / Mapper / Service / Controller
- Vue 列表页、表单页

生成后调整：

- `selected_branches`、`extra` 使用 JSON 类型或 String 存储
- 凭证表仅单条记录（id=1），表单按「编辑」而非「新增」

---

## 五、与 RootSeeker 的 HTTP 对接

### 5.1 需调用的接口

| 接口 | 方法 | 用途 |
|------|------|------|
| `/git-source/config` | PUT | 保存凭证并拉取仓库列表 |
| `/git-source/repos` | GET | 获取仓库列表（可选，也可直接查表） |
| `/git-source/repos/{id}` | GET | 获取仓库详情与分支 |
| `/git-source/repos/{id}` | PUT | 配置分支、启用/禁用 |
| `/git-source/sync` | POST | 同步所有已启用仓库 |

### 5.2 鉴权

RootSeeker 使用 `X-Api-Key`。若依需在调用时携带：

```java
// 若依侧 RestTemplate / OkHttp 等
headers.set("X-Api-Key", rootSeekerApiKey);
```

`rootSeekerApiKey` 可配置在若依的 `application.yml`：

```yaml
root-seeker:
  base-url: http://localhost:8000  # RootSeeker 服务地址
  api-key: ${ROOT_SEEKER_API_KEY:your-api-key}
```

### 5.3 若依侧封装示例

```java
@Service
public class RootSeekerClient {
    @Value("${root-seeker.base-url}")
    private String baseUrl;
    @Value("${root-seeker.api-key}")
    private String apiKey;

    public void connectAndFetchRepos(String domain, String username, String password) {
        // PUT /git-source/config
        // body: { domain, username, password }
    }

    public void syncRepos() {
        // POST /git-source/sync
    }

    public List<Branch> getBranches(String repoId) {
        // GET /git-source/repos/{repoId}
    }
}
```

---

## 六、环境要求与一键启动

### 6.1 必须安装的组件与版本

| 组件 | 版本要求 | 说明 |
|------|----------|------|
| Python | ≥ 3.11 | RootSeeker 核心 |
| JDK | 8 | RootSeeker Admin（若依） |
| Maven | 3.x | RootSeeker Admin 构建 |
| Go | 最新 | Zoekt 词法检索 |
| Qdrant | v1.16.3 | 向量库（安装脚本自动下载） |
| Zoekt | latest | 词法检索（安装脚本自动安装） |

**可选**：MySQL（当 git_source 使用 MySQL 存储或 config_source=database 时）

### 6.2 一键启动与停止

| 平台 | 启动 | 停止 |
|------|------|------|
| **macOS / Linux** | `bash scripts/start-all-one-click.sh` | `bash scripts/stop-all-one-click.sh` |
| **Windows** | `scripts\start-all-one-click.bat` | `scripts\stop-all-one-click.bat` |
| **Docker** | `cd root_seeker_docker && docker compose up -d` | `docker compose down` |

| 服务 | 地址 | 说明 |
|------|------|------|
| RootSeeker | http://localhost:8000 | Python FastAPI 分析服务 |
| RootSeeker Admin | http://localhost:8080 | 若依管理端 |
| Qdrant | http://localhost:6333 | 向量库 |
| Zoekt | http://localhost:6070 | 词法检索 |

日志输出到 `logs/` 目录（qdrant.log、zoekt.log、root-seeker.log、root-seeker-admin.log）。

**前置条件**：执行 `bash scripts/install-without-docker.sh` 安装 Qdrant、Zoekt；Zoekt 需先执行 `bash scripts/index-zoekt-all.sh` 为仓库建索引。

---

## 七、项目结构（已实现）

```
ai-log-helper/
├── root_seeker/                  # Python RootSeeker 核心
├── config.yaml
├── docs/
└── ruoyi-rootseeker-admin/       # 若依管理端（与 root_seeker 平级）
    ├── ruoyi-admin/               # Web 入口
    ├── ruoyi-system/              # 含 GitSource 域、Mapper、Service
    ├── sql/
    │   ├── git_source.sql         # 表结构
    │   └── git_source_menu.sql    # 菜单
    └── README_ROOTSEEKER.md       # 使用说明
```

---

## 八、实施步骤

1. **克隆若依**：`git clone https://gitee.com/y_project/RuoYi-Vue.git ruoyi-rootseeker-admin`
2. **配置数据库**：指向 RootSeeker 使用的 MySQL，执行若依初始化 SQL
3. **创建 git_source 表**：若 RootSeeker 未初始化，可手动执行建表 SQL（与 `mysql_storage.py` 中一致）
4. **代码生成**：为 `git_source_repos`、`git_source_credential` 生成 CRUD
5. **开发 RootSeekerClient**：封装对 RootSeeker 的 HTTP 调用
6. **菜单与页面**：新增「Git 仓库管理」菜单，列表页增加「拉取列表」「同步」按钮并调用 Client
7. **配置**：在若依中配置 `root-seeker.base-url`、`root-seeker.api-key`

---

## 九、优缺点

### 优点

- 使用成熟的若依脚手架，权限、菜单、日志齐全
- 前后端分离，Vue + Element UI 体验好
- 与 RootSeeker 解耦，可独立部署、升级
- 共享 MySQL，无需数据同步

### 注意点

- 需保证 `git_source_*` 表结构与 RootSeeker 一致
- 凭证、拉取、同步等写操作需与 RootSeeker 约定好谁为主（建议以 RootSeeker 为准，若依仅通过 API 触发）
- 若依与 RootSeeker 需能互相访问（同机或内网）

---

*文档生成时间：2025-02-03*
