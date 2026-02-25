#!/usr/bin/env python3
"""
从一条 SLS 原始日志（JSON）解析出 IngestEvent 参数并调用 POST /ingest/aliyun-sls，
再轮询 GET /analysis/{analysis_id} 直到拿到报告或超时。
用法: python3 scripts/ingest-one-sls-log.py < sls_log.json
或:   python3 scripts/ingest-one-sls-log.py --file sls_log.json
"""
from __future__ import annotations

import argparse
import json
import sys
import time
from urllib.request import Request, urlopen
from urllib.error import HTTPError, URLError

from root_seeker.ingest import parse_sls_record

DEFAULT_BASE = "http://127.0.0.1:8000"


def main() -> None:
    ap = argparse.ArgumentParser(description="Parse SLS log and call ingest, then poll analysis")
    ap.add_argument("--base", default=DEFAULT_BASE, help="Base URL of RootSeeker")
    ap.add_argument("--file", "-f", help="Read SLS JSON from file (default: stdin)")
    ap.add_argument("--poll-interval", type=float, default=2.0, help="Poll interval seconds")
    ap.add_argument("--poll-max", type=int, default=120, help="Max poll count (default 120 = 4 min)")
    args = ap.parse_args()
    base = args.base.rstrip("/")

    if args.file:
        with open(args.file, "r", encoding="utf-8") as f:
            raw = json.load(f)
    else:
        raw = json.load(sys.stdin)

    # 若外层是列表则取第一条
    if isinstance(raw, list) and raw:
        raw = raw[0]
    event = parse_sls_record(raw)
    body_json = event.model_dump_json(exclude_none=True)

    # POST /ingest 或 /ingest/aliyun-sls 均可
    req = Request(
        f"{base}/ingest",
        data=body_json.encode("utf-8"),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urlopen(req, timeout=30) as r:
            resp = json.loads(r.read().decode("utf-8"))
    except (HTTPError, URLError) as e:
        print("ingest 请求失败:", e, file=sys.stderr)
        if isinstance(e, HTTPError) and e.read:
            try:
                print(e.read().decode("utf-8"), file=sys.stderr)
            except Exception:
                pass
        sys.exit(1)

    if resp.get("status") != "accepted":
        print("ingest 未返回 accepted:", resp, file=sys.stderr)
        sys.exit(1)
    analysis_id = resp.get("analysis_id")
    if not analysis_id:
        print("缺少 analysis_id:", resp, file=sys.stderr)
        sys.exit(1)
    print("已提交:", "analysis_id =", analysis_id)
    print("轮询 GET /analysis/" + analysis_id + " ...")

    # 轮询 GET /analysis/{analysis_id}
    for i in range(args.poll_max):
        time.sleep(args.poll_interval)
        req = Request(f"{base}/analysis/{analysis_id}", method="GET")
        try:
            with urlopen(req, timeout=10) as r:
                data = json.loads(r.read().decode("utf-8"))
        except HTTPError as e:
            if e.code == 404:
                continue
            print("轮询失败:", e, file=sys.stderr)
            continue
        except URLError as e:
            print("轮询失败:", e, file=sys.stderr)
            continue

        status = data.get("status")
        # 完成：显式 status=completed 或返回了报告（含 summary）
        if (status == "completed" or "summary" in data) and "summary" in data:
            print("\n--- 分析报告 ---")
            print("summary:", data.get("summary", ""))
            if data.get("hypotheses"):
                print("hypotheses:", data.get("hypotheses"))
            if data.get("suggestions"):
                print("suggestions:", data.get("suggestions"))
            if data.get("related_services"):
                print("related_services:", data.get("related_services"))
            print("\n完整 JSON 已写入 stdout，可重定向到文件。")
            print(json.dumps(data, ensure_ascii=False, indent=2))
            return
        if status in ("failed", "error"):
            print("分析失败:", data, file=sys.stderr)
            sys.exit(1)
        print(f"  [{i+1}] status={status or data}")

    print("轮询超时，未拿到最终报告。analysis_id =", analysis_id, file=sys.stderr)
    sys.exit(1)


if __name__ == "__main__":
    main()
