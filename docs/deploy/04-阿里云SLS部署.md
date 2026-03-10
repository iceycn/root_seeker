# 阿里云 SLS 配置与打通

RootSeeker 通过「Webhook 携带 query_key + 事件时间」用 SQL 模板向阿里云日志服务（SLS）拉取更多日志，用于分析时的上下文补全。

## 1. 前置条件

- 已开通阿里云日志服务 SLS，并创建好 **Project** 与 **Logstore**。
- 拥有可访问该 Project/Logstore 的 **AccessKey ID / AccessKey Secret**（建议使用 RAM 子账号，权限最小化）。

## 2. 在 config.yaml 中配置

```yaml
aliyun_sls:
  endpoint: "https://cn-hangzhou.log.aliyuncs.com"   # 按地域替换
  access_key_id: "YOUR_AK"
  access_key_secret: "YOUR_SK"
  project: "your-sls-project"
  logstore: "your-logstore"
  topic: null   # 若 SLS 按 topic 区分可填

sql_templates:
  - query_key: "default_error_context"
    query: "level:ERROR and service:{service_name} | select * from log where __time__ >= {start_ts} and __time__ <= {end_ts} limit 200"
```

- **query_key**：与 Webhook 入参 `query_key` 一致；每条事件可带不同 query_key，对应不同 SQL 模板。
- **query**：SLS 查询语法，支持占位符：`{service_name}`、`{start_ts}`、`{end_ts}` 等，由 enricher 根据事件时间窗与事件内容注入。

## 3. Webhook 入参说明

调用 `POST /ingest`（通用）或 `POST /ingest/aliyun-sls`（兼容 SLS 原始格式）时，JSON 建议包含：

- **service_name**（必填）：用于路由仓库及 SQL 中的 service 条件。
- **error_log**（必填）：原始错误日志/堆栈，供分析与检索使用。
- **query_key**（必填）：对应 `sql_templates` 中某一项的 `query_key`，用于选取 SQL 模板。
- **timestamp**（可选）：错误发生时间，若不传则用服务端当前时间；用于计算 `start_ts`/`end_ts` 时间窗。
- **tags**（可选）：扩展字段，如 env、trace_id 等。

## 4. 与业务打通方式

- **方式一（推荐）**：在阿里云 SLS 控制台配置「告警 / 触发」→ 投递到「自定义 Webhook」，请求体构造为上述 JSON，URL 填 `http://<host>:8000/ingest` 或 `http://<host>:8000/ingest/aliyun-sls`。
- **方式二**：业务侧或中间层在产生错误时直接调用 `POST /ingest`，传入相同结构的 JSON。

若需鉴权，在 config 中配置 `api_keys`，并在 Webhook 请求头中加上 `X-API-Key: <key>`。

## 5. 时间窗说明

- enricher 会根据事件的 `timestamp` 与配置的时间窗（如 300 秒）计算 `start_ts`、`end_ts`，并替换到 SQL 模板中。
- **注意**：当前 `providers/sls.py` 内调用 SLS 的 `get_log` 时，若仍使用「当前时间」作为 from_time/to_time，则与事件时间不一致，会导致补全不到正确时间段日志。建议按 [优化清单.md](../优化清单.md) 将 `from_ts`/`to_ts` 传入 SLS 查询接口（若 SDK 支持），或使用 SLS 的查询 API 并传入模板中已替换好的时间范围。

## 6. 安全

- AK/SK 仅保存在 config 或密钥管理服务中，不要写入代码或日志。
- 建议使用 RAM 角色或短期密钥，并限制仅能访问指定 Project/Logstore。
