# RootSeeker 应用傻瓜部署

本服务是错误分析与代码检索的核心，需在 Zoekt、Qdrant（可选）及配置就绪后部署。

## 1. 环境要求

- Python 3.11+
- 内网可访问：Zoekt（若启用）、Qdrant（若启用）、阿里云 SLS（若启用）、LLM API（DeepSeek/豆包）、企业微信/钉钉 Webhook（若启用）
- Git 已安装，且运行用户对 `repos[].local_dir` 有读写权限

## 2. 安装依赖

在项目根目录执行：

```bash
pip install -e .
# 或
pip install -r pyproject.toml  # 若已导出 requirements
```

主要依赖：fastapi、uvicorn、pydantic、httpx、pyyaml、aliyun-log-python-sdk、qdrant-client、tree-sitter、tree-sitter-python、tree-sitter-java、fastembed。

**不依赖 Docker 一键安装（含 Python 依赖 + Go + Zoekt + Qdrant 二进制）**：在项目根目录执行 `bash scripts/install-without-docker.sh`，按脚本末尾提示启动 Qdrant、Zoekt 与本应用。若 `go install` 超时，可设置 `GOPROXY=https://goproxy.cn,direct` 后重试。详见 [README.md](../README.md)「本机安装」。

## 3. 配置文件

```bash
cp config.example.yaml config.yaml
# 按实际环境修改 config.yaml
```

必改项（至少满足最小可运行）：

- **aliyun_sls**：endpoint、access_key_id、access_key_secret、project、logstore（若不用 SLS，需改代码将此项改为可选，见 [00-overview.md](00-overview.md)）。
- **repos**：至少一条，填写 service_name、git_url、local_dir；local_dir 所在目录需存在且可写。
- **sql_templates**：至少一条 query_key（如 `default_error_context`）及对应 SLS 查询语句。

可选：

- **zoekt**：填写 `api_base_url`（如 `http://zoekt-host:6070`），不填则不做词法检索。
- **qdrant**：填写 `url`、`collection`，不填则不做向量检索与索引。
- **llm**：base_url、api_key、model（DeepSeek/豆包等 OpenAI 兼容 API），不填则报告为固定文案。
- **wecom** 或 **dingtalk**：webhook_url，不填则不推送通知。
- **api_keys**：若配置列表非空，请求需带 `X-API-Key`。

## 4. 启动服务

```bash
export ROOT_SEEKER_CONFIG_PATH=/path/to/config.yaml  # 可选，默认 config.yaml
python -m uvicorn main:app --host 0.0.0.0 --port 8000
```

或指定 workers（多进程）：

```bash
python -m uvicorn main:app --host 0.0.0.0 --port 8000 --workers 2
```

## 5. 验证

```bash
curl -s http://127.0.0.1:8000/healthz
# 期望：{"status":"ok"}
```

若配置了 api_keys，其他接口需带 Header：`X-API-Key: <your_key>`。

## 6. 部署后必做步骤（按需）

1. **同步仓库**  
   `POST /repos/sync`（可带 `service_name` 只同步单个），将 Git 仓库拉到各 `local_dir`。

2. **Zoekt 索引**  
   对每个 `local_dir` 按 [01-zoekt.md](01-zoekt.md) 建 Zoekt 索引，并保证 Zoekt 服务已启动且 `config.yaml` 中 `zoekt.api_base_url` 正确。

3. **向量索引**  
   若启用了 Qdrant 与 embedding，对每个服务执行：  
   `POST /index/repo/{service_name}`，将代码块写入 Qdrant。

4. **依赖图**  
   `POST /graph/rebuild`，根据本地仓库代码生成上下游依赖图，供报告「关联服务」使用。

## 7. 数据与日志

- 分析结果与任务状态：`config.yaml` 中 `data_dir` 下的 `analyses`、`status`。
- 审计日志：`audit_dir` 下（若配置）。
- 依赖图文件：`data_dir/service_graph.json`（由 `POST /graph/rebuild` 生成）。

## 8. 进程管理（示例 systemd）

```ini
[Unit]
Description=RootSeeker
After=network.target

[Service]
Type=simple
User=app
WorkingDirectory=/opt/RootSeeker
Environment=ROOT_SEEKER_CONFIG_PATH=/opt/RootSeeker/config.yaml
ExecStart=/usr/bin/python3 -m uvicorn main:app --host 0.0.0.0 --port 8000
Restart=on-failure

[Install]
WantedBy=multi-user.target
```

将 `User`、`WorkingDirectory`、`ExecStart` 改为实际路径与解释器即可。
