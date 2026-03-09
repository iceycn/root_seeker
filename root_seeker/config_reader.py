"""配置读取器：支持 file / database 双模式，MySQL 模式下从 app_config 表读取配置。"""
from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

import yaml

logger = logging.getLogger(__name__)
from pydantic_settings import BaseSettings, SettingsConfigDict


class _ReaderSettings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="ROOT_SEEKER_", extra="ignore")
    config_path: Path = Path("config.yaml")


def _read_yaml(path: Path) -> dict[str, Any]:
    if not path.exists():
        raise FileNotFoundError(f"Config file not found: {path}")
    raw = yaml.safe_load(path.read_text(encoding="utf-8"))
    if raw is None:
        return {}
    if not isinstance(raw, dict):
        raise ValueError("Config file must contain a YAML mapping at the root.")
    return raw


def _get_config_db_from_yaml(raw: dict[str, Any]) -> dict[str, Any] | None:
    """从 yaml 获取数据库连接配置。各项目维护自己的 config.yaml，不跨项目读取。"""
    def _norm(db: dict) -> dict[str, Any]:
        return {
            "host": db.get("host", "localhost"),
            "port": int(db.get("port", 3306)),
            "user": db.get("user") or db.get("username", "root"),
            "password": db.get("password", ""),
            "database": db.get("database", "root_seeker"),
        }

    if raw.get("config_db") and isinstance(raw["config_db"], dict) and raw["config_db"].get("host"):
        return _norm(raw["config_db"])
    gs = raw.get("git_source") or {}
    storage = gs.get("storage") if isinstance(gs, dict) else {}
    if isinstance(storage, dict) and storage.get("type") == "mysql" and storage.get("host"):
        return _norm(storage)
    return None


def _deep_merge(base: dict[str, Any], override: dict[str, Any]) -> dict[str, Any]:
    """深度合并 override 到 base，override 优先。"""
    result = dict(base)
    for k, v in override.items():
        if k in result and isinstance(result[k], dict) and isinstance(v, dict):
            result[k] = _deep_merge(result[k], v)
        else:
            result[k] = v
    return result


class ConfigReader:
    """
    配置读取器：根据 config_source 选择 file 或 database 模式。
    - file：从 config.yaml 读取
    - database：从 config.yaml 读取 config_db 连接信息，再从 app_config 表加载配置并合并
    """

    def __init__(self, config_path: Path | None = None) -> None:
        settings = _ReaderSettings()
        self._config_path = config_path or settings.config_path

    def read(self) -> dict[str, Any]:
        """
        读取完整配置（已合并）。
        - file 模式：返回 yaml 内容（移除 config_source、config_db）
        - database 模式：yaml + app_config 表合并，app_config 优先
        """
        raw = _read_yaml(self._config_path)

        config_source = raw.get("config_source") or "file"
        if isinstance(config_source, str):
            config_source = config_source.strip().lower()
        else:
            config_source = "file"

        if config_source == "database":
            config_db = _get_config_db_from_yaml(raw)
            if config_db:
                try:
                    from root_seeker.config_db import load_config_from_db

                    db_config = load_config_from_db(
                        host=config_db.get("host", "localhost"),
                        port=int(config_db.get("port", 3306)),
                        user=config_db.get("user", "root"),
                        password=config_db.get("password", ""),
                        database=config_db.get("database", "root_seeker"),
                    )
                    raw = _deep_merge(raw, db_config)
                    logger.info("[ConfigReader] 已从 app_config 表加载配置并合并")
                except Exception as e:
                    logger.warning(
                        "[ConfigReader] 从数据库加载配置失败，回退到 YAML: %s",
                        e,
                        exc_info=True,
                    )

        # 移除 bootstrap 字段，避免 Pydantic 校验
        raw.pop("config_source", None)
        raw.pop("config_db", None)
        return raw


def get_config_db(raw: dict[str, Any] | None = None) -> dict[str, Any] | None:
    """获取数据库连接配置。若 raw 为 None 则从 config_path 读取。供 API 等使用。"""
    if raw is None:
        raw = _read_yaml(_ReaderSettings().config_path)
    return _get_config_db_from_yaml(raw)
