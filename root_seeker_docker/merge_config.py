#!/usr/bin/env python3
"""合并 config.docker.yaml 到 config.yaml，用于 Docker 环境下 qdrant.url 等配置。"""
import sys

def main():
    if len(sys.argv) < 3:
        sys.exit(1)
    config_path = sys.argv[1]
    docker_config_path = sys.argv[2]
    try:
        import yaml
    except ImportError:
        sys.exit(1)
    with open(config_path, encoding="utf-8") as f:
        cfg = yaml.safe_load(f) or {}
    with open(docker_config_path, encoding="utf-8") as f:
        docker_cfg = yaml.safe_load(f) or {}

    def merge(a, b):
        for k, v in b.items():
            if k in a and isinstance(a[k], dict) and isinstance(v, dict):
                merge(a[k], v)
            else:
                a[k] = v

    merge(cfg, docker_cfg)

    # Docker 下修正 repos[].local_dir 为 /app/data/repos/<service_name>
    for repo in cfg.get("repos", []):
        if isinstance(repo, dict) and "service_name" in repo and "local_dir" in repo:
            sn = repo["service_name"]
            repo["local_dir"] = f"/app/data/repos/{sn}"

    with open(config_path, "w", encoding="utf-8") as f:
        yaml.dump(cfg, f, allow_unicode=True, default_flow_style=False, sort_keys=False)

if __name__ == "__main__":
    main()
