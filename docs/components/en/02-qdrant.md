# Qdrant Setup

Qdrant is the **vector store** for code. RootSeeker uses it for indexing and semantic retrieval.

## Config

In `config.yaml`:

```yaml
qdrant:
  url: "http://127.0.0.1:6333"
  api_key: null
  collection: "code_chunks"
```

## Install

**Docker:**

```bash
docker run -d --name qdrant -p 6333:6333 -v /data/qdrant_storage:/qdrant/storage:z qdrant/qdrant
```

**macOS binary:** `bash scripts/install-without-docker.sh`

## Start

```bash
./tools/qdrant --config-path config/qdrant_config.yaml
```

## Vector Indexing

```bash
# Single repo
curl -X POST "http://127.0.0.1:8000/index/repo/order-service"

# All repos
python3 scripts/index-all-repos.py
```

## Verify

```bash
curl -s http://127.0.0.1:6333/collections
python3 scripts/check-vector-index.py
```

## Troubleshooting

- **0 retrieval**: Run `check-vector-index.py`; ensure `POST /index/repo/{service_name}` was run for that service.
- **Slow indexing**: First run loads Embedding model; large repos may take time.

[中文](../02-qdrant.md)
