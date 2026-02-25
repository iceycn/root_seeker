# Aliyun SLS Setup

RootSeeker uses Aliyun Log Service (SLS) to fetch more logs for context enrichment.

## Config

In `config.yaml`:

```yaml
aliyun_sls:
  endpoint: "https://cn-hangzhou.log.aliyuncs.com"
  access_key_id: "YOUR_AK"
  access_key_secret: "YOUR_SK"
  project: "your-sls-project"
  logstore: "your-logstore"

sql_templates:
  - query_key: "default_error_context"
    query: "level:ERROR and service:{service_name} | select * from log where __time__ >= {start_ts} and __time__ <= {end_ts} limit 200"
```

Placeholders: `{service_name}`, `{start_ts}`, `{end_ts}`, `{trace_id}`, `{request_id}`.

## Webhook

Configure SLS Webhook to `http://<host>:8000/ingest` or `/ingest/aliyun-sls`. Body: `service_name`, `error_log`, `query_key`, optional `timestamp`.

[中文](../03-aliyun-sls.md)
