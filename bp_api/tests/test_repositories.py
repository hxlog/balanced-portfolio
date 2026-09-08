"""repositories 单元测试(不依赖真实 PostgreSQL)。"""

from __future__ import annotations

from contextlib import contextmanager
from datetime import date
from unittest.mock import MagicMock

import pandas as pd

from bp_api.repositories import list_data_sources, upsert_asset_config
from bp_api.schemas import AssetAdminIn, AssetProbeIn


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


# ---------------------------------------------------------------------
# Task 3: list_data_sources 透出 is_addable
# ---------------------------------------------------------------------
def test_list_data_sources_selects_and_casts_is_addable():
    """SELECT 须带 is_addable 列, 且返回 dict 中为原生 bool(futures_cffex 过滤的依据)。"""
    with _mock_conn() as (conn, cur):
        cur.fetchall.return_value = [
            ("cn_index_em", "A股指数-东财", "cn_index", "000300", True, True, "东财", "cn_index", False, True),
            ("futures_cffex", "中金所期货日行情", "futures", "IF/IH/IC/IM", True, True, "中金所", "futures_cffex", False, False),
        ]
        out = list_data_sources(conn)
    sql = " ".join(cur.execute.call_args[0][0].split())
    assert "is_addable" in sql
    by_code = {d["code"]: d for d in out}
    assert by_code["cn_index_em"]["is_addable"] is True
    assert by_code["futures_cffex"]["is_addable"] is False


# ---------------------------------------------------------------------
# Task 3: probe 端点透传 extra_params 给 fetch_with_fallback
# ---------------------------------------------------------------------
def _probe_df():
    return pd.DataFrame(
        {
            "trade_date": [date(2026, 9, 1), date(2026, 9, 2)],
            "open": [10.0, 10.5],
            "high": [10.5, 10.8],
            "low": [9.9, 10.2],
            "close": [10.2, 10.6],
            "volume": [1000, 1100],
            "amount": [None, None],
            "turnover_rate": [None, None],
            "pct_change": [None, None],
        }
    )


def _run_probe(payload):
    """直接驱动 probe_admin_asset handler: mock fetch_with_fallback / db / refresh_asset_status,
    返回 (响应, fetch_with_fallback 收到的 extra 参数列表)。"""
    from unittest.mock import patch

    from bp_api import main

    received: list[dict] = []

    def _fake_fetch(source, symbol, start, end, extra=None, **kwargs):
        received.append(dict(extra or {}))
        return _probe_df()

    conn = MagicMock()

    @contextmanager
    def _get_conn():
        yield conn

    with patch.object(main.db, "get_conn", _get_conn), \
         patch.object(main.repo, "refresh_asset_status", lambda *a, **k: None), \
         patch("bp_ingest.sources.fetch_with_fallback", _fake_fetch):
        out = main.probe_admin_asset("etf_em", "510300", payload)
    return out, received


def test_probe_admin_asset_passes_extra_params_through():
    """body 带 extra_params 时原样透传给 fetch_with_fallback(ETF 复权口径真实生效)。"""
    payload = AssetProbeIn(extra_params={"adjust": "hfq"})
    out, received = _run_probe(payload)
    assert out["ok"] is True
    assert out["rows"] == 2
    assert received == [{"adjust": "hfq"}]


def test_probe_admin_asset_defaults_to_empty_extra_when_body_missing():
    """body 缺省(payload=None)时 extra={} —— 与旧行为完全向后兼容。"""
    out, received = _run_probe(None)
    assert out["ok"] is True
    assert received == [{}]


def test_probe_admin_asset_empty_body_defaults_extra_params_dict():
    """body 为 {} 时 AssetProbeIn.extra_params 默认 dict() → extra={}。"""
    out, received = _run_probe(AssetProbeIn())
    assert out["ok"] is True
    assert received == [{}]
