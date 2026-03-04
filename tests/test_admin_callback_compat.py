"""Admin updateFromCallback 逻辑兼容性测试（Python 模拟）。

验证 RootSeeker 发送的 payload 能被 Admin 的 updateFromCallback 正确解析。
Admin 实现见 RepoIndexStatusServiceImpl.updateFromCallback。
状态：未索引|索引中|已索引|清理中
"""

from __future__ import annotations

S_NOT = "未索引"
S_INDEXING = "索引中"
S_INDEXED = "已索引"
S_REMOVING = "清理中"


def _get_str_py(m: dict, key: str) -> str:
    v = m.get(key)
    return str(v).strip() if v is not None else ""


def _get_int(m: dict, key: str, default: int) -> int:
    v = m.get(key)
    if v is None:
        return default
    if isinstance(v, (int, float)):
        return int(v)
    try:
        return int(str(v))
    except (ValueError, TypeError):
        return default


def _parse_bool(m: dict, key: str) -> bool:
    v = m.get(key)
    if v is None:
        return False
    if isinstance(v, bool):
        return v
    return str(v).lower() == "true"


def update_from_callback_simulated(payload: dict | None) -> dict | None:
    """模拟 Admin RepoIndexStatusServiceImpl.updateFromCallback 的核心逻辑（单字段状态）。"""
    if payload is None:
        return None
    sn = payload.get("service_name")
    if sn is None or not str(sn).strip():
        return None
    service_name = str(sn).strip()

    status: dict = {
        "service_name": service_name,
        "qdrant_status": S_NOT,
        "qdrant_count": 0,
        "zoekt_status": S_NOT,
    }

    task_type = _get_str_py(payload, "task_type")
    task_status = _get_str_py(payload, "status")

    if task_type == "qdrant":
        if task_status == "completed":
            status["qdrant_status"] = S_INDEXED
            status["qdrant_count"] = _get_int(payload, "qdrant_count", 0)
    elif task_type == "zoekt":
        if task_status == "completed":
            status["zoekt_status"] = S_INDEXED
    elif task_type in ("remove_qdrant", "remove_zoekt"):
        if task_status == "completed":
            if task_type == "remove_qdrant":
                status["qdrant_status"] = S_NOT
                status["qdrant_count"] = 0
            else:
                status["zoekt_status"] = S_NOT
    elif task_type == "resync":
        if task_status == "completed":
            qi = _get_int(payload, "qdrant_indexed", 1)
            status["qdrant_status"] = S_INDEXED if qi else S_NOT
            status["qdrant_count"] = _get_int(payload, "qdrant_count", 0)
            zi = _get_int(payload, "zoekt_indexed", 1)
            status["zoekt_status"] = S_INDEXED if zi else S_NOT
    elif task_type == "sync":
        qs = _get_str_py(payload, "qdrant_status")
        if qs:
            status["qdrant_status"] = qs
        else:
            q_rm = _parse_bool(payload, "qdrant_removing")
            q_ng = _parse_bool(payload, "qdrant_indexing")
            q_i = _parse_bool(payload, "qdrant_indexed")
            status["qdrant_status"] = S_REMOVING if q_rm else (S_INDEXING if q_ng else (S_INDEXED if q_i else S_NOT))
        status["qdrant_count"] = _get_int(payload, "qdrant_count", 0)
        zs = _get_str_py(payload, "zoekt_status")
        if zs:
            status["zoekt_status"] = zs
        else:
            z_rm = _parse_bool(payload, "zoekt_removing")
            z_ng = _parse_bool(payload, "zoekt_indexing")
            z_i = _parse_bool(payload, "zoekt_indexed")
            status["zoekt_status"] = S_REMOVING if z_rm else (S_INDEXING if z_ng else (S_INDEXED if z_i else S_NOT))

    return status


class TestAdminCallbackCompat:
    """验证 RootSeeker payload 与 Admin 解析逻辑兼容。"""

    def test_qdrant_completed(self) -> None:
        payload = {
            "service_name": "api-distribution",
            "task_type": "qdrant",
            "status": "completed",
            "qdrant_indexed": 1,
            "qdrant_count": 100,
        }
        out = update_from_callback_simulated(payload)
        assert out is not None
        assert out["qdrant_status"] == S_INDEXED
        assert out["qdrant_count"] == 100
        assert out["zoekt_status"] == S_NOT

    def test_zoekt_completed(self) -> None:
        payload = {
            "service_name": "api-distribution",
            "task_type": "zoekt",
            "status": "completed",
            "zoekt_indexed": 1,
        }
        out = update_from_callback_simulated(payload)
        assert out is not None
        assert out["zoekt_status"] == S_INDEXED
        assert out["qdrant_status"] == S_NOT

    def test_remove_qdrant_completed(self) -> None:
        payload = {
            "service_name": "api-distribution",
            "task_type": "remove_qdrant",
            "status": "completed",
            "qdrant_indexed": 0,
        }
        out = update_from_callback_simulated(payload)
        assert out is not None
        assert out["qdrant_status"] == S_NOT
        assert out["qdrant_count"] == 0

    def test_remove_zoekt_completed(self) -> None:
        payload = {
            "service_name": "api-distribution",
            "task_type": "remove_zoekt",
            "status": "completed",
            "zoekt_indexed": 0,
        }
        out = update_from_callback_simulated(payload)
        assert out is not None
        assert out["zoekt_status"] == S_NOT

    def test_empty_service_name_ignored(self) -> None:
        payload = {"service_name": "", "task_type": "qdrant", "status": "completed"}
        assert update_from_callback_simulated(payload) is None

    def test_null_payload_ignored(self) -> None:
        assert update_from_callback_simulated(None) is None

    def test_qdrant_count_from_int(self) -> None:
        payload = {
            "service_name": "test",
            "task_type": "qdrant",
            "status": "completed",
            "qdrant_indexed": 1,
            "qdrant_count": 50,
        }
        out = update_from_callback_simulated(payload)
        assert out["qdrant_count"] == 50

    def test_rootseeker_payload_format_matches_admin(self) -> None:
        """验证 RootSeeker IndexCallbackTrigger 发出的 payload 格式与 Admin 期望一致。"""
        rootseeker_payloads = [
            {
                "service_name": "api-distribution",
                "task_type": "qdrant",
                "status": "completed",
                "qdrant_indexed": 1,
                "qdrant_count": 100,
            },
            {
                "service_name": "api-distribution",
                "task_type": "zoekt",
                "status": "completed",
                "zoekt_indexed": 1,
            },
            {
                "service_name": "api-distribution",
                "task_type": "remove_qdrant",
                "status": "completed",
                "qdrant_indexed": 0,
            },
            {
                "service_name": "api-distribution",
                "task_type": "remove_zoekt",
                "status": "completed",
                "zoekt_indexed": 0,
            },
        ]
        for payload in rootseeker_payloads:
            out = update_from_callback_simulated(payload)
            assert out is not None, f"payload 应被正确解析: {payload}"
            assert out["service_name"] == "api-distribution"


def test_service_name_matching() -> None:
    """模拟 Admin getIndexStatus 的 service_name 匹配逻辑。"""
    status_map = {
        "api-distribution": {"qdrant_status": S_INDEXED, "zoekt_status": S_INDEXED},
    }

    def find_status(sn: str) -> dict | None:
        st = status_map.get(sn)
        if st is None:
            st = status_map.get(sn.replace("_", "-"))
        if st is None:
            st = status_map.get(sn.replace("-", "_"))
        return st

    assert find_status("api-distribution") is not None
    assert find_status("api_distribution") is not None
    assert find_status("api-distribution").get("qdrant_status") == S_INDEXED
