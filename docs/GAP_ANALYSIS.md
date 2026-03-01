# 项目漏洞与不足分析

基于对整体代码库的审查，整理出以下问题与改进建议。

---

## 一、安全漏洞

### 1.1 鉴权缺口

| 问题 | 位置 | 说明 | 状态 |
|------|------|------|------|
| **GET /graph 无鉴权** | `app.py` | 返回完整服务依赖图，未使用 `require_api_key` | ✅ 已修复 |
| **api_keys 为空时全接口无鉴权** | `security.py` | `allowed` 为空时直接 return，所有接口无需鉴权。生产环境应强制配置 | 待改进 |

### 1.2 敏感数据存储

| 问题 | 位置 | 说明 | 状态 |
|------|------|------|------|
| **Git 凭证明文存储** | `git_source/storage/file_storage.py` | 凭证（domain、username、password）以明文写入 JSON | 待改进 |
| **config.yaml 含敏感信息** | 配置 | AK/SK、webhook、token 等均明文，建议文档说明权限与 gitignore | 待改进 |

### 1.3 输入校验与路径安全

| 问题 | 位置 | 说明 | 状态 |
|------|------|------|------|
| **git_source repo_id 未校验** | `app.py` | `repo_id` 来自 `{repo_id}` 路径参数，未限制长度与字符 | ✅ 已修复 |
| **local_dir 路径遍历** | `git_source/service.py` | `full_name` 若含 `..` 可能构造非法路径 | ✅ 已修复 |
| **file_path 存储** | `git_source/__init__.py` | `create_storage_from_config` 的 `file_path` 未校验 | ✅ 已修复 |
| **EvidenceBuilder 路径遍历** | `evidence.py` | `_read_file_region` 未校验 file_path 是否在 repo 内；`build_from_zoekt_hits` 的 startswith 检查有前缀漏洞 | 待修复 |

---

## 二、功能缺陷

### 2.1 错误处理

| 问题 | 位置 | 说明 | 状态 |
|------|------|------|------|
| **FileStorage load 静默失败** | `file_storage.py` | `load()` 异常时返回空数据，未记录日志 | ✅ 已修复 |
| **MySQL 连接失败** | `mysql_storage.py` | 未做连接重试或健康检查，启动时若 MySQL 不可用可能直接失败 | 待改进 |
| **AnalysisStore/StatusStore load 无异常处理** | `analysis_store.py`, `status_store.py` | JSON 解析失败时直接抛出，无日志，可考虑 try/except 并记录 | 待改进 |

### 2.2 缺失能力（按 OPTIMIZATION_CHECKLIST）

| 项 | 说明 | 优先级 |
|----|------|--------|
| **证据包脱敏** | 方案要求对 AK/SK、Token、Cookie 等脱敏，当前未实现 | P2 |
| **白名单控制外发** | 仅允许指定 repo/service 外发 LLM，当前未实现 | P2 |
| **审计日志轮转** | 单文件追加，易导致文件过大 | P3 |

### 2.3 限流与防护

| 问题 | 位置 | 说明 |
|------|------|------|
| **Ingest 无限流** | `app.py` | POST /ingest 可被高频调用，易耗尽队列与资源 |
| **batch-cluster 无并发限制** | `app.py` | 单次 5000 条限制存在，但无全局并发限制，多请求可同时压测 |
| **API 无 rate limit** | 全局 | 无基于 IP 或 token 的限流 |

---

## 三、健壮性不足

### 3.1 Git 源

| 问题 | 位置 | 说明 |
|------|------|------|
| **catalog 启动时固定** | `app.py` | `repos_for_catalog` 在启动时读取，git_source 新增仓库后需重启才能参与分析 |
| **update_repo 匹配逻辑** | `file_storage.py` | `update_repo` 仅按 `r.id == repo.id` 匹配，Codeup 等平台 id 可能变化 |
| **GitLab 分支获取** | `gitlab.py` | 用 `search` 查找 project，可能匹配不到或匹配错误 |

### 3.2 其他

| 问题 | 位置 | 说明 | 状态 |
|------|------|------|------|
| **repos/sync 未包含 git_source** | `app.py` | `POST /repos/sync` 使用 `cfg.repos`，未同步 git_source 已启用仓库 | ✅ 已修复 |
| **graph/rebuild 未包含 git_source** | `app.py` | `POST /graph/rebuild` 使用 `cfg.repos`，依赖图不包含 git_source 仓库 | ✅ 已修复 |
| **健康检查不完整** | `app.py` | `healthz?check_deps=true` 未检查 SLS、LLM 可达性 | 待改进 |

---

## 四、本次 Review 新增发现

### 4.1 安全

| 问题 | 位置 | 说明 |
|------|------|------|
| **EvidenceBuilder 路径遍历** | `evidence.py` | `_read_file_region` 直接拼接 `repo_local_dir + file_path`，未校验解析后路径是否在 repo 内；`build_from_zoekt_hits` 使用 `str(full_path).startswith(str(repo_path))` 有前缀漏洞（如 `/data/repo` 与 `/data/repo_evil`） |
| **IngestEvent 无长度限制** | `domain.py` | `service_name`、`error_log` 无 max_length，超大 payload 可能导致内存/存储压力 |

### 4.2 健壮性

| 问题 | 位置 | 说明 |
|------|------|------|
| **graph/rebuild 遗漏 git_source** | `app.py` | 与 repos/sync 类似，依赖图重建仅用 `cfg.repos` | ✅ 已修复 |
| **AnalysisStore/StatusStore JSON 解析** | `analysis_store.py`, `status_store.py` | 损坏的 JSON 文件会直接抛异常，无友好错误信息 |

### 4.3 逻辑一致性

| 问题 | 位置 | 说明 |
|------|------|------|
| **catalog 与 sync/rebuild 数据源不一致** | `app.py` | catalog、periodic 使用 `repos_for_catalog`（含 git_source），但 `POST /repos/sync`、`POST /graph/rebuild` 仅用 `cfg.repos` | ✅ 已修复 |

---

## 五、改进建议（按优先级）

### P0（安全）— 大部分已修复

1. ~~**鉴权**：为 `GET /graph` 增加 `require_api_key`~~ ✅
2. ~~**repo_id 校验**~~ ✅
3. ~~**local_dir 校验**~~ ✅
4. **EvidenceBuilder 路径校验**：修复 `_read_file_region` 与 `build_from_zoekt_hits` 的路径遍历漏洞

### P1（功能）

1. **repos/sync 合并 git_source**：`POST /repos/sync` 同步时包含 git_source 已启用仓库
2. **graph/rebuild 合并 git_source**：依赖图重建时包含 git_source 仓库
3. **catalog 动态更新**：支持通过接口或定时任务刷新 catalog，无需重启
4. ~~**FileStorage 加载失败日志**~~ ✅

### P2（安全增强）

1. **凭证加密**：对 Git 凭证做加密存储（如 AES），密钥由环境变量或密钥服务提供
2. **证据包脱敏**：在 EvidenceBuilder 或 LLM 前增加脱敏规则
3. **白名单控制**：增加 `allow_llm_export_services` 配置，控制可外发 LLM 的服务

### P3（运维）

1. **Ingest 限流**：按 IP 或 API Key 限流，如 100 req/min
2. **审计日志轮转**：按日或按大小轮转，或对接日志平台
3. **健康检查扩展**：增加 SLS、LLM 可达性检查

---

## 六、已做得较好的部分

- [x] `analysis_id`、`service_name` 等 API 输入校验（防注入）
- [x] `AnalysisStore.path_for`、`StatusStore.path_for` 路径遍历防护
- [x] `EvidenceBuilder.build_from_zoekt_hits` 有路径校验（但存在前缀漏洞，见 1.3）
- [x] 分析超时与 job 失败处理
- [x] 审计日志记录 LLM 调用
- [x] Git 凭证、repo_id、local_dir、file_path 等安全修复已完成

---

*文档更新时间：2025-02-03，基于完整项目 Review*
