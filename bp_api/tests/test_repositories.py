"""repositories 单元测试(不依赖真实 PostgreSQL)。"""

from __future__ import annotations

from contextlib import contextmanager
from unittest.mock import MagicMock

from bp_api.repositories import upsert_asset_config
from bp_api.schemas import AssetAdminIn


@contextmanager
def _mock_conn():
    cur = MagicMock()
    conn = MagicMock()
    conn.cursor.return_value.__enter__ = MagicMock(return_value=cur)
    conn.cursor.return_value.__exit__ = MagicMock(return_value=False)
    yield conn, cur


def _call_upsert(**kwargs) -> tuple[str, dict]:
    payload = AssetAdminIn(
        symbol=kwargs.get("symbol", "HSMSI"),
        source=kwargs.get("source", "hk_index_em"),
        name=kwargs.get("name", "恒生综合中小型股指数"),
        category=kwargs.get("category", "index"),
        start_date=kwargs.get("start_date"),
        is_deleted=kwargs.get("is_deleted", 0),
        adjust=kwargs.get("adjust"),
    )
    with _mock_conn() as (conn, cur):
        upsert_asset_config(conn, payload)
    sql, params = cur.execute.call_args[0]
    return sql, params


def test_upsert_asset_config_adjust_none_uses_empty_json_patch():
    sql, params = _call_upsert(adjust=None)
    assert params["extra_patch"] == "{}"
    assert "jsonb_build_object('adjust'" not in sql
    assert "%(extra_patch)s::jsonb" in sql


def test_upsert_asset_config_adjust_hfq_serializes_patch():
    sql, params = _call_upsert(adjust="hfq", category="etf")
    assert params["extra_patch"] == '{"adjust": "hfq"}'
    assert "jsonb_build_object('adjust'" not in sql
    assert "%(extra_patch)s::jsonb" in sql
