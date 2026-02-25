# RootSeeker

AI-powered error analysis and root cause discovery for internal services: SLS (Webhook + enrichment) → Zoekt (lexical search) → Qdrant (vector search) → LLM (DeepSeek/Doubao) → WeChat/DingTalk notifications.

**[中文文档](README.md)** | English

## Quick Start

```bash
# 1. Copy config
cp config.example.yaml config.yaml

# 2. Edit config.yaml (at least repos, aliyun_sls, llm, etc.)

# 3. One-click install (Python + Go + Zoekt + Qdrant)
bash scripts/install-without-docker.sh

# 4. Start in order (see "Startup Order" below)
```

## Startup Order

| Step | Component | Command |
|------|-----------|---------|
| 1 | Qdrant | `./tools/qdrant --config-path config/qdrant_config.yaml` |
| 2 | Zoekt | Run `bash scripts/index-zoekt-all.sh` first to build index, then `zoekt-webserver -index data/zoekt/index -listen :6070` |
| 3 | App | `python3 -m uvicorn main:app --host 0.0.0.0 --port 8000` |

Verify: `bash scripts/check-services.sh` or `curl http://127.0.0.1:8000/healthz`

## Component Docs (Step-by-Step)

Each component has its own page with config, setup, and troubleshooting:

| Component | Doc | Description |
|-----------|-----|-------------|
| **Config Reference** | [docs/components/en/00-config-reference.md](docs/components/en/00-config-reference.md) | Full config key list |
| **Zoekt** | [docs/components/en/01-zoekt.md](docs/components/en/01-zoekt.md) | Lexical search: config, install, index repos |
| **Qdrant** | [docs/components/en/02-qdrant.md](docs/components/en/02-qdrant.md) | Vector store: config, code indexing |
| **Aliyun SLS** | [docs/components/en/03-aliyun-sls.md](docs/components/en/03-aliyun-sls.md) | Log enrichment: AK/SK, project, logstore, SQL templates |
| **LLM** | [docs/components/en/04-llm.md](docs/components/en/04-llm.md) | DeepSeek/Doubao, timeout, retry |
| **Embedding** | [docs/components/en/05-embedding.md](docs/components/en/05-embedding.md) | Code vectorization |
| **Repos** | [docs/components/en/06-repos.md](docs/components/en/06-repos.md) | Repo config, sync, indexing flow |
| **Notifiers** | [docs/components/en/07-notifiers.md](docs/components/en/07-notifiers.md) | WeChat/DingTalk Webhook |
| **Data Storage** | [docs/components/en/08-data-storage.md](docs/components/en/08-data-storage.md) | File-based storage, no database |

## API Overview

| Endpoint | Description |
|----------|-------------|
| `POST /ingest` | Submit error log (generic JSON) |
| `POST /ingest/aliyun-sls` | Submit error log (SLS raw format) |
| `GET /analysis/{analysis_id}` | Query analysis result |
| `POST /repos/sync` | Sync/pull repos (git clone/pull) |
| `POST /index/repo/{service_name}` | Build vector index for a repo |
| `POST /graph/rebuild` | Rebuild service dependency graph |

## Authentication

If `api_keys` is configured in `config.yaml`, requests must include: `X-API-Key: <your_key>`

## More Docs

- [Deployment Overview](docs/deploy/00-overview.md)
- [Documentation Index](docs/DOCUMENTATION_INDEX.md)
