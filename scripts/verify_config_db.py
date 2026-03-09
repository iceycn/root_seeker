#!/usr/bin/env python3
"""验证 MySQL 模式下配置能否正确加载到 RootSeeker。
用法：在项目根目录执行 python scripts/verify_config_db.py
      或 Docker 内：ROOT_SEEKER_CONFIG_PATH=/app/config.yaml python -c "
        import sys; sys.path.insert(0,'/app');
        from root_seeker.config_reader import ConfigReader
        from root_seeker.config_db import load_config_from_db
        r = ConfigReader()
        raw = r.read()
        print('config_source:', raw.get('_config_source_','N/A'))
        print('qdrant:', raw.get('qdrant'))
        print('zoekt:', raw.get('zoekt'))
        print('llm:', raw.get('llm'))
        print('config_db present:', 'config_db' in raw)
      "
"""
import os
import sys

# 确保项目根目录在 path 中
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


def main():
    config_path = os.environ.get("ROOT_SEEKER_CONFIG_PATH", "config.yaml")
    if not os.path.exists(config_path):
        print(f"[FAIL] 配置文件不存在: {config_path}")
        return 1

    from pathlib import Path
    from root_seeker.config_reader import ConfigReader, _get_config_db_from_yaml, _read_yaml

    raw_yaml = _read_yaml(Path(config_path))
    config_source = (raw_yaml.get("config_source") or "file").strip().lower()
    config_db = _get_config_db_from_yaml(raw_yaml)

    print("=== 配置加载验证 ===\n")
    print(f"1. config_path: {config_path}")
    print(f"2. config_source (yaml): {config_source}")
    print(f"3. config_db 连接信息: {config_db or '未配置'}")

    if config_source != "database":
        print("\n[SKIP] config_source 不是 database，跳过数据库加载验证")
        return 0

    if not config_db or not config_db.get("host"):
        print("\n[FAIL] config_source=database 但 config_db 未配置或缺少 host")
        return 1

    try:
        from root_seeker.config_db import load_config_from_db

        db_config = load_config_from_db(
            host=config_db.get("host", "localhost"),
            port=int(config_db.get("port", 3306)),
            user=config_db.get("user", "root"),
            password=config_db.get("password", ""),
            database=config_db.get("database", "root_seeker"),
        )
        print(f"\n4. 从 app_config 加载的配置分类: {list(db_config.keys())}")

        for cat in ["qdrant", "zoekt", "llm", "embedding", "aliyun_sls", "git_source"]:
            val = db_config.get(cat)
            if val is not None:
                print(f"   - {cat}: {str(val)[:80]}...")
            else:
                print(f"   - {cat}: (未找到)")

        # 模拟 ConfigReader 的合并
        def _deep_merge(base, override):
            result = dict(base)
            for k, v in override.items():
                if k in result and isinstance(result[k], dict) and isinstance(v, dict):
                    result[k] = _deep_merge(result[k], v)
                else:
                    result[k] = v
            return result

        merged = _deep_merge(raw_yaml, db_config)
        merged.pop("config_source", None)
        merged.pop("config_db", None)

        from root_seeker.config import AppConfig

        app = AppConfig.model_validate(merged)
        print("\n5. Pydantic 校验通过，配置已正确解析")
        print(f"   - qdrant.url: {app.qdrant.url if app.qdrant else 'N/A'}")
        print(f"   - zoekt.api_base_url: {app.zoekt.api_base_url if app.zoekt else 'N/A'}")
        print(f"   - llm.model: {app.llm.model if app.llm else 'N/A'}")
        print(f"   - git_source.enabled: {app.git_source.enabled if app.git_source else 'N/A'}")

        return 0
    except Exception as e:
        print(f"\n[FAIL] 加载或校验失败: {e}")
        import traceback
        traceback.print_exc()
        return 1


if __name__ == "__main__":
    sys.exit(main())
