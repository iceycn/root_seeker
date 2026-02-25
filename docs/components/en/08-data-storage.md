# Data Storage

RootSeeker **does not use a database**. All data is stored as JSON files.

## Structure

```
data/
├── analyses/          # Analysis reports
├── status/            # Task status (pending/running/completed/failed)
├── service_graph.json # Dependency graph
├── qdrant_storage/    # Qdrant data
└── zoekt/index/       # Zoekt index
```

## No DB Init

- No MySQL/PostgreSQL; no schema scripts.
- Directories are created automatically on first write.
- Qdrant collection is created on first `POST /index/repo/{service_name}`.

[中文](../08-data-storage.md)
