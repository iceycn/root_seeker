# Data Storage

RootSeeker stores analysis results and job status on local disk by default (`data_dir`). However, the whole project supports multiple storage/config modes and may involve MySQL in some scenarios.

## Modes

| Mode | Needs MySQL | Components | Notes |
|------|-------------|------------|------|
| A. File-only (default) | No | RootSeeker | Analyses, status, service graph are stored as JSON files |
| B. Git source with MySQL (optional) | Yes | RootSeeker | When `git_source.storage.type=mysql`, RootSeeker reads/writes MySQL for repos/credentials |
| C. Admin + config DB (common in Docker) | Yes | RootSeeker Admin | Admin requires MySQL; Docker often enables `config_source=database` to store config in `app_config` |

## Structure

```
data/
├── analyses/          # Analysis reports
├── status/            # Task status (pending/running/completed/failed)
├── service_graph.json # Dependency graph
├── qdrant_storage/    # Qdrant data
└── zoekt/index/       # Zoekt index
```

## No DB Init (Mode A)

- No MySQL/PostgreSQL; no schema scripts.
- Directories are created automatically on first write.
- Qdrant collection is created on first `POST /index/repo/{service_name}`.

If you use Mode B/C, follow the Admin and Docker deployment docs.

[中文](../08-data-storage.md)
