#!/usr/bin/env python3
"""
诊断向量检索为 0 的原因。
检查：1) Qdrant 是否可达 2) collection 是否存在 3) 是否有数据 4) service_name 分布
用法: python3 scripts/check-vector-index.py [--service SERVICE_NAME]
"""
from __future__ import annotations

import argparse
import sys

from root_seeker.config import load_config
from root_seeker.providers.qdrant import QdrantConfig, QdrantVectorStore


def main() -> None:
    ap = argparse.ArgumentParser(description="诊断向量索引状态")
    ap.add_argument("--service", "-s", help="检查指定 service_name 是否有数据")
    args = ap.parse_args()

    cfg = load_config()
    qcfg_app = cfg.app.qdrant
    if qcfg_app is None:
        print("[FAIL] config.yaml 中未配置 qdrant")
        sys.exit(1)
    qcfg = QdrantConfig(
        url=qcfg_app.url,
        api_key=qcfg_app.api_key,
        collection=qcfg_app.collection,
    )
    store = QdrantVectorStore(qcfg)
    client = store._client

    print(f"Qdrant URL: {qcfg.url}")
    print(f"Collection: {qcfg.collection}")
    print()

    # 1. 检查连接
    try:
        collections = client.get_collections().collections
        print("[OK] Qdrant 连接正常")
    except Exception as e:
        print(f"[FAIL] Qdrant 连接失败: {e}")
        print("  请确认 Qdrant 已启动: docker run -p 6333:6333 qdrant/qdrant")
        sys.exit(1)

    # 2. 检查 collection 是否存在
    if not client.collection_exists(collection_name=qcfg.collection):
        print(f"[FAIL] Collection '{qcfg.collection}' 不存在")
        print("  请先对仓库执行索引: POST /index/repo/{service_name}")
        sys.exit(1)
    print(f"[OK] Collection '{qcfg.collection}' 存在")

    # 3. 获取数量
    info = client.get_collection(collection_name=qcfg.collection)
    count = info.points_count or 0
    print(f"  总向量数: {count}")

    if count == 0:
        print()
        print("[原因] 向量库为空，检索必然返回 0")
        print("  解决: 对需要分析的仓库执行索引，例如:")
        for r in cfg.app.repos[:5]:
            print(f"    curl -X POST 'http://127.0.0.1:8000/index/repo/{r.service_name}'")
        if len(cfg.app.repos) > 5:
            print(f"    ... 共 {len(cfg.app.repos)} 个仓库")
        sys.exit(0)

    # 4. 抽样查看 service_name 分布
    scroll = client.scroll(
        collection_name=qcfg.collection,
        limit=100,
        with_payload=True,
    )
    points = scroll[0] or []
    service_names = set()
    repo_dirs = set()
    for p in points:
        payload = p.payload or {}
        service_names.add(payload.get("service_name", ""))
        repo_dirs.add(payload.get("repo_local_dir", ""))
    service_names.discard("")
    repo_dirs.discard("")

    print()
    print("索引中的 service_name 示例:", sorted(service_names)[:15])
    if repo_dirs:
        print("索引中的 repo_local_dir 示例:", list(repo_dirs)[:3])

    # 5. 若指定了 service，检查该 service 是否有数据
    if args.service:
        from qdrant_client.http.models import Filter, FieldCondition, MatchValue

        qfilter = Filter(must=[FieldCondition(key="service_name", match=MatchValue(value=args.service))])
        scroll = client.scroll(
            collection_name=qcfg.collection,
            scroll_filter=qfilter,
            limit=1,
            with_payload=True,
        )
        matched = len(scroll[0] or [])
        if matched > 0:
            print()
            print(f"[OK] service_name='{args.service}' 有数据")
        else:
            print()
            print(f"[FAIL] service_name='{args.service}' 无数据")
            print(f"  可能原因: 1) 未对该仓库执行索引 2) 索引时用的 service_name 与检索时不一致")
            print(f"  解决: curl -X POST 'http://127.0.0.1:8000/index/repo/{args.service}'")


if __name__ == "__main__":
    main()
