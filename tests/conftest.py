"""pytest 共享 fixture：最小化配置与 TestClient。"""

from __future__ import annotations

import os
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

# 测试用最小化 config 路径（相对项目根）
TESTS_DIR = Path(__file__).resolve().parent
CONFIG_MINIMAL = TESTS_DIR / "fixtures" / "config_minimal.yaml"


@pytest.fixture(scope="session")
def test_config_path(tmp_path_factory):
    """生成带临时 data_dir 的测试 config，避免污染项目 data。"""
    tmp = tmp_path_factory.mktemp("rs_test")
    data_dir = tmp / "data"
    data_dir.mkdir()
    (data_dir / "analyses").mkdir()
    (data_dir / "status").mkdir()
    audit_dir = tmp / "audit"
    audit_dir.mkdir()
    cfg_path = tmp / "config.yaml"
    content = CONFIG_MINIMAL.read_text(encoding="utf-8")
    content += f"\ndata_dir: {data_dir}\naudit_dir: {audit_dir}\n"
    cfg_path.write_text(content, encoding="utf-8")
    return cfg_path


@pytest.fixture
def app_client(test_config_path):
    """使用测试 config 的 TestClient。通过 ROOT_SEEKER_CONFIG_PATH 指定配置。"""
    with pytest.MonkeyPatch.context() as m:
        m.setenv("ROOT_SEEKER_TEST", "1")
        m.setenv("ROOT_SEEKER_CONFIG_PATH", str(test_config_path))
        from root_seeker.app import create_app

        app = create_app()
        with TestClient(app) as client:
            yield client
