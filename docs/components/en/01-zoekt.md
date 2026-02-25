# Zoekt Setup

Zoekt provides **lexical/symbol search** for code. RootSeeker uses it to locate relevant files and lines during error analysis.

## Config

In `config.yaml`:

```yaml
zoekt:
  api_base_url: "http://127.0.0.1:6070"
```

- Omit `zoekt` to skip lexical search (vector + stacktrace only).

## Install

```bash
go install github.com/google/zoekt/cmd/zoekt-index@latest
go install github.com/google/zoekt/cmd/zoekt-webserver@latest
export PATH="$(go env GOPATH)/bin:$PATH"
```

Or use `bash scripts/install-without-docker.sh`.

## Index Repos

```bash
# Sync repos first
curl -X POST "http://127.0.0.1:8000/repos/sync"

# Build all indexes
bash scripts/index-zoekt-all.sh
```

Manual single repo:

```bash
zoekt-index -index "$ZOOKT_INDEX_DIR" -repo_name "order-service" /data/repos/order-service
```

Use `-repo_name` matching `service_name` in config.

## Start Zoekt

```bash
zoekt-webserver -index data/zoekt/index -listen :6070
```

## Verify

```bash
curl -s -X POST "http://127.0.0.1:6070/api/search" \
  -H "Content-Type: application/json" \
  -d '{"Q":"Exception","Opts":{"NumContextLines":3,"MaxMatchCount":10}}'
```

## Troubleshooting

- **"No local file content from Zoekt hits"**: `local_dir` must match the path used when indexing; `repo_name` should match `service_name`.
- **0 hits**: Check query terms exist in code; verify repo name matches.

[中文](../01-zoekt.md)
