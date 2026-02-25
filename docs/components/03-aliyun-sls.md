# 阿里云 SLS 配置指南

RootSeeker 通过阿里云日志服务（SLS）拉取更多日志，用于分析时的上下文补全和调用链查询。

## 一、配置项说明

在 `config.yaml` 中：

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
  - query_key: "trace_chain"
    query: "(trace_id:{trace_id} or request_id:{request_id}) | select * from log where __time__ >= {start_ts} and __time__ <= {end_ts} order by __time__ asc limit 500"
```

### 字段说明

| 字段 | 说明 |
|------|------|
| endpoint | SLS API 地址，按地域选择（如 cn-hangzhou、cn-beijing） |
| access_key_id | 阿里云 AccessKey ID（建议 RAM 子账号） |
| access_key_secret | AccessKey Secret |
| project | SLS 项目名 |
| logstore | Logstore 名 |
| topic | 可选，若日志按 topic 区分可填 |
| sql_templates | 查询模板列表，每条含 query_key 和 query |

### SQL 模板占位符

- `{service_name}`：从 Webhook 入参或日志解析得到
- `{start_ts}`、`{end_ts}`：根据事件时间与时间窗计算
- `{trace_id}`、`{request_id}`：从错误日志中提取（调用链查询用）

## 二、前置条件

- 已开通阿里云日志服务 SLS
- 已创建 Project 与 Logstore
- 拥有可访问的 AccessKey（建议 RAM 子账号，权限最小化）

## 三、Webhook 入参

调用 `POST /ingest` 或 `POST /ingest/aliyun-sls` 时，JSON 需包含：

| 字段 | 必填 | 说明 |
|------|------|------|
| service_name | 是 | 服务名，用于路由仓库及 SQL 中的 service 条件 |
| error_log | 是 | 原始错误日志/堆栈 |
| query_key | 是 | 对应 sql_templates 中的 query_key，默认 `default_error_context` |
| timestamp | 否 | 错误发生时间，不传则用服务端当前时间 |
| tags | 否 | 扩展字段 |

## 四、与业务打通

### 方式一：SLS 控制台 Webhook（推荐）

在阿里云 SLS 控制台配置「告警 / 触发」→ 投递到「自定义 Webhook」：

- URL：`http://<RootSeeker 主机>:8000/ingest` 或 `/ingest/aliyun-sls`
- 请求体：构造上述 JSON 格式

### 方式二：业务侧直接调用

业务或中间层在产生错误时直接调用 `POST /ingest`，传入相同结构的 JSON。

### 鉴权

若 config 中配置了 `api_keys`，Webhook 请求头需加：`X-API-Key: <key>`

## 五、安全建议

- AK/SK 仅保存在 config 或密钥管理服务，不要写入代码或日志
- 使用 RAM 角色或短期密钥
- 限制仅能访问指定 Project/Logstore

[English](en/03-aliyun-sls.md)
