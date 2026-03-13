"""配置热更新测试：reload_config_raw。"""

from __future__ import annotations

import threading
from pathlib import Path

import pytest
import yaml

from root_seeker.config_reader import reload_config_raw


def test_reload_config_raw_concurrent_lock(tmp_path):
    """TC-CFG-002: 并发 reload 时 Lock 串行，无竞态。"""
    base_cfg = {
        "data_dir": "data1",
        "audit_dir": "audit1",
        "aliyun_sls": {
            "endpoint": "https://cn-hangzhou.log.aliyuncs.com",
            "access_key_id": "a",
            "access_key_secret": "s",
            "project": "p",
            "logstore": "l",
        },
        "sql_templates": [],
    }
    cfg_path = tmp_path / "config.yaml"
    cfg_path.write_text(yaml.dump(base_cfg), encoding="utf-8")

    results = []
    errors = []

    def reload_and_record():
        try:
            raw = reload_config_raw(cfg_path)
            results.append(raw.get("data_dir"))
        except Exception as e:
            errors.append(e)

    threads = [threading.Thread(target=reload_and_record) for _ in range(10)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    assert not errors
    assert len(results) == 10
    assert all(r == "data1" for r in results)


def test_reload_config_raw_returns_new_config(tmp_path):
    """TC-CFG-001: reload_config_raw 返回新配置。"""
    cfg_path = tmp_path / "config.yaml"
    base_cfg = {
        "data_dir": "data1",
        "audit_dir": "audit1",
        "aliyun_sls": {
            "endpoint": "https://cn-hangzhou.log.aliyuncs.com",
            "access_key_id": "a",
            "access_key_secret": "s",
            "project": "p",
            "logstore": "l",
        },
        "sql_templates": [],
    }
    cfg_path.write_text(yaml.dump(base_cfg), encoding="utf-8")

    raw1 = reload_config_raw(cfg_path)
    assert raw1.get("data_dir") == "data1"

    base_cfg["data_dir"] = "data2"
    cfg_path.write_text(yaml.dump(base_cfg), encoding="utf-8")
    raw2 = reload_config_raw(cfg_path)
    assert raw2.get("data_dir") == "data2"
    assert raw1.get("data_dir") != raw2.get("data_dir")
