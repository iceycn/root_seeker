#!/usr/bin/env python3
"""
对所有 config 中的仓库执行向量索引。
用法: python3 scripts/index-all-repos.py [--base URL] [--dry-run]
"""
from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path
from urllib.request import Request, urlopen
from urllib.error import HTTPError, URLError

# 添加项目根目录到 path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from root_seeker.config import load_config

DEFAULT_BASE = "http://127.0.0.1:8000"


def main() -> None:
    ap = argparse.ArgumentParser(description="对所有仓库执行向量索引")
    ap.add_argument("--base", default=DEFAULT_BASE, help="RootSeeker 服务地址")
    ap.add_argument("--dry-run", action="store_true", help="仅打印将要索引的仓库，不实际执行")
    ap.add_argument("--api-key", help="若配置了 api_keys，传入 X-API-Key")
    args = ap.parse_args()

    cfg = load_config()
    base = args.base.rstrip("/")
    repos = cfg.app.repos
    if not repos:
        print("config 中无 repos 配置")
        sys.exit(0)

    headers = {"Content-Type": "application/json"}
    if args.api_key:
        headers["X-API-Key"] = args.api_key

    print(f"共 {len(repos)} 个仓库待索引")
    if args.dry_run:
        for r in repos:
            print(f"  - {r.service_name}: {r.local_dir}")
        return

    ok = 0
    fail = 0
    for i, r in enumerate(repos, 1):
        url = f"{base}/index/repo/{r.service_name}"
        req = Request(url, data=b"", headers=headers, method="POST")
        try:
            t0 = time.time()
            with urlopen(req, timeout=600) as resp:
                data = json.loads(resp.read().decode("utf-8"))
            elapsed = time.time() - t0
            count = data.get("indexed_chunks", 0)
            print(f"[{i}/{len(repos)}] {r.service_name}: {count} 块, 耗时 {elapsed:.1f}s")
            ok += 1
        except HTTPError as e:
            body = ""
            try:
                body = e.read().decode("utf-8")
            except Exception:
                pass
            print(f"[{i}/{len(repos)}] {r.service_name}: 失败 {e.code} - {body[:200]}")
            fail += 1
        except URLError as e:
            print(f"[{i}/{len(repos)}] {r.service_name}: 连接失败 - {e.reason}")
            fail += 1
        except Exception as e:
            print(f"[{i}/{len(repos)}] {r.service_name}: 异常 - {e}")
            fail += 1

    print()
    print(f"完成: 成功 {ok}, 失败 {fail}")


if __name__ == "__main__":
    main()
