"""MCP 配置节点名兼容：mcpServers 映射为 mcp.servers。"""

from __future__ import annotations

import tempfile
from pathlib import Path

import pytest
import yaml

from root_seeker.config import AppConfig
from root_seeker.config_reader import ConfigReader


def test_mcp_servers_alias_maps_to_mcp_servers():
    """mcpServers 节点名兼容：config 含 mcpServers 时映射为 mcp.servers。"""
    base = {
        "data_dir": "data",
        "audit_dir": "audit",
        "aliyun_sls": {
            "endpoint": "https://cn-hangzhou.log.aliyuncs.com",
            "access_key_id": "a",
            "access_key_secret": "s",
            "project": "p",
            "logstore": "l",
        },
        "sql_templates": [],
        "mcpServers": {
            "aliyun": {
                "command": "npx",
                "args": ["-y", "@aliyun/mcp-server"],
                "transport": "stdio",
            },
        },
    }
    with tempfile.NamedTemporaryFile(mode="w", suffix=".yaml", delete=False) as f:
        yaml.dump(base, f, allow_unicode=True)
        path = Path(f.name)
    try:
        raw = ConfigReader(config_path=path).read()
        assert "mcpServers" not in raw
        assert "mcp" in raw
        assert raw["mcp"]["servers"]["aliyun"]["command"] == "npx"
    finally:
        path.unlink(missing_ok=True)
