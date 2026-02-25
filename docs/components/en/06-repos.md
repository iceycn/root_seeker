# Repo Config

RootSeeker maps service names to local repos via `repos` config.

## Config

```yaml
repos:
  - service_name: "order-service"
    git_url: "https://git.example.com/org/order-service.git"
    local_dir: "/data/repos/order-service"
    repo_aliases: ["order"]
    language_hints: ["python"]
```

## Init Flow

1. Add repos in `config.yaml`
2. Sync: `POST /repos/sync`
3. Zoekt index: `bash scripts/index-zoekt-all.sh`
4. Vector index: `POST /index/repo/{service_name}` or `python3 scripts/index-all-repos.py`
5. Optional: `POST /graph/rebuild` for dependency graph

**Important:** `local_dir` must match the path used for Zoekt indexing.

[中文](../06-repos.md)
