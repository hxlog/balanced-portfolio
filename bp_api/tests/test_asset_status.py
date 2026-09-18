"""Task 4: refresh_asset_status with_count 分级 + list_assets/list_admin_assets 透出 currency。

单元测试(mock 连接, 不依赖真实 PostgreSQL):
- with_count=False: 只跑 MAX(trade_date), upsert 不含 raw_rows/clean_rows → 不覆盖既有校准值;
- with_count=True: MAX+COUNT 都跑, upsert 写回真实行数;
- last_success_at COALESCE 语义两分支一致;
- list_assets / list_admin_assets SELECT 带 c.currency 且返回 dict 含 currency 键;
- ingest SyncResult.advanced 门控(推进才重算 COUNT)。
"""

from __future__ import annotations

import os
from contextlib import contextmanager
from datetime import date
from unittest.mock import MagicMock

import pytest


@contextmanager
def _mock_conn():
    cur = MagicMock()
    conn = MagicMock()
    conn.cursor.return_value.__enter__ = MagicMock(return_value=cur)
    conn.cursor.return_value.__exit__ = MagicMock(return_value=False)
    yield conn, cur


def _execs(cur) -> list[str]:
    """每次 execute 的 SQL 文本(拼接换行归一)。"""
    return [" ".join(c[0][0].split()) for c in cur.execute.call_args_list]


# ---------------------------------------------------------------------
# refresh_asset_status: with_count 分级
# ---------------------------------------------------------------------
def test_refresh_asset_status_without_count_runs_only_max_queries():
    """with_count=False: 两条 SELECT 只有 MAX(trade_date), 不含 COUNT(*); upsert 不含 raw_rows/clean_rows。"""
    from bp_api.repositories import refresh_asset_status

    with _mock_conn() as (conn, cur):
        cur.fetchone.side_effect = [(date(2026, 9, 4),), (date(2026, 9, 4),)]
        refresh_asset_status(conn, "510300", "etf_em")
    sqls = _execs(cur)
    assert len(sqls) == 3  # 2 条 MAX + 1 条 upsert
    assert "COUNT(*)" not in sqls[0] and "MAX(trade_date)" in sqls[0]
    assert "COUNT(*)" not in sqls[1] and "MAX(trade_date)" in sqls[1]
    upsert = sqls[2]
    assert "INSERT INTO bp_asset_data_status" in upsert
    assert "raw_rows" not in upsert and "clean_rows" not in upsert
    # last_success_at 的 COALESCE 语义保持不变
    assert "last_success_at=COALESCE(EXCLUDED.last_success_at, bp_asset_data_status.last_success_at)" in upsert
    # 参数化, 无字符串拼接: upsert 占位符 7 个(success_at 为 now() 非空)
    params = cur.execute.call_args_list[2][0][1]
    assert params[:4] == ("510300", "etf_em", date(2026, 9, 4), date(2026, 9, 4))
    assert params[4] is not None  # success_at(error=None → now)
    assert params[5] is None and params[6] is None  # error / probe_ms


def test_refresh_asset_status_without_count_upsert_preserves_existing_rows():
    """热路径 upsert 不得触碰 raw_rows/clean_rows: DO UPDATE SET 列表中无两列名,
    既有校准值(如 999)在 UPDATE 分支原样保留, INSERT 新行靠 DEFAULT 0。"""
    from bp_api.repositories import refresh_asset_status

    with _mock_conn() as (conn, cur):
        cur.fetchone.side_effect = [(date(2026, 9, 4),), (date(2026, 9, 4),)]
        refresh_asset_status(conn, "510300", "etf_em", error=None, probe_ms=120, with_count=False)
    upsert = _execs(cur)[2]
    do_update = upsert.split("DO UPDATE SET", 1)[1]
    assert "raw_rows" not in do_update and "clean_rows" not in do_update
    assert "last_raw_date=EXCLUDED.last_raw_date" in do_update  # 日期照常推进
    params = cur.execute.call_args_list[2][0][1]
    assert params[2] == date(2026, 9, 4) and params[3] == date(2026, 9, 4)
    assert params[4] is not None  # success_at(error=None → now)
    assert params[5] is None and params[6] == 120  # error / probe_ms


def test_refresh_asset_status_with_count_writes_real_counts():
    """with_count=True: MAX+COUNT 都查, upsert 含 raw_rows/clean_rows 写回真实行数(现状行为)。"""
    from bp_api.repositories import refresh_asset_status

    with _mock_conn() as (conn, cur):
        cur.fetchone.side_effect = [
            (date(2026, 9, 4), 1500),   # raw MAX + COUNT
            (date(2026, 9, 4), 1498),   # clean MAX + COUNT
        ]
        refresh_asset_status(conn, "510300", "etf_em", with_count=True)
    sqls = _execs(cur)
    assert len(sqls) == 3
    assert "COUNT(*)" in sqls[0] and "MAX(trade_date)" in sqls[0]
    assert "COUNT(*)" in sqls[1] and "MAX(trade_date)" in sqls[1]
    upsert = sqls[2]
    assert "raw_rows=EXCLUDED.raw_rows" in upsert
    assert "clean_rows=EXCLUDED.clean_rows" in upsert
    params = cur.execute.call_args_list[2][0][1]
    assert params[:6] == ("510300", "etf_em", date(2026, 9, 4), date(2026, 9, 4), 1500, 1498)
    assert params[6] is not None  # success_at(error=None → now)
    assert params[7] is None and params[8] is None  # error / probe_ms


def test_refresh_asset_status_default_is_without_count():
    """签名默认 with_count=False: probe/保存/巡检等既有调用不传参即走热路径。"""
    import inspect

    from bp_api.repositories import refresh_asset_status

    sig = inspect.signature(refresh_asset_status)
    assert sig.parameters["with_count"].default is False
    assert sig.parameters["with_count"].kind is inspect.Parameter.KEYWORD_ONLY


def test_refresh_asset_status_count_queries_are_parameterized():
    """两分支全部 SQL 参数化(%s 占位), 无 f-string/format 拼接注入面。"""
    from bp_api.repositories import refresh_asset_status

    for kwargs in ({}, {"with_count": True}):
        with _mock_conn() as (conn, cur):
            cur.fetchone.side_effect = [(date(2026, 1, 1), 1), (date(2026, 1, 1), 1)]
            refresh_asset_status(conn, "A;b", "src", **kwargs)
        for call in cur.execute.call_args_list:
            sql, params = call[0]
            assert "A;b" not in sql  # 值只经参数传递
            assert params and "A;b" in params


# ---------------------------------------------------------------------
# 真实 PostgreSQL 语义验证(BP_TEST_DSN 未设置时跳过, CI 无 Postgres 仍绿)
# ---------------------------------------------------------------------
_real_db = pytest.mark.skipif(
    not os.environ.get("BP_TEST_DSN"),
    reason="real-DB semantics test; set BP_TEST_DSN=postgresql://user:pass@host/db to run",
)


@_real_db
def test_with_count_semantics_real_db():
    """真实库验证保存语义: False 分支保留既有 raw_rows/clean_rows 并推进日期;
    True 分支写回真实 COUNT/MAX(无行情行 → 0/NULL)。"""
    import psycopg

    from bp_api import repositories as repo

    dsn = os.environ["BP_TEST_DSN"]
    with psycopg.connect(dsn, autocommit=False) as conn:
        with conn.cursor() as cur:
            # 隔离测试资产行(既有校准值 999/999)
            cur.execute(
                "DELETE FROM bp_asset_data_status WHERE symbol=%s AND source=%s",
                ("__T4_TEST__", "__t4__"),
            )
            cur.execute(
                """INSERT INTO bp_asset_data_status
                     (symbol, source, last_raw_date, last_clean_date, raw_rows, clean_rows)
                   VALUES (%s,%s,%s,%s,999,999)""",
                ("__T4_TEST__", "__t4__", date(2020, 1, 1), date(2020, 1, 1)),
            )
        conn.commit()
        try:
            # False 分支: 不触碰 raw_rows/clean_rows, 但推进 last_raw_date(无行情 → None)
            repo.refresh_asset_status(conn, "__T4_TEST__", "__t4__")
            conn.commit()
            with conn.cursor() as cur:
                cur.execute(
                    "SELECT raw_rows, clean_rows FROM bp_asset_data_status WHERE symbol=%s AND source=%s",
                    ("__T4_TEST__", "__t4__"),
                )
                assert cur.fetchone() == (999, 999)
            # True 分支: 对该 (symbol,source) 真实 COUNT(无行情行 → 0), MAX → None
            repo.refresh_asset_status(conn, "__T4_TEST__", "__t4__", with_count=True)
            conn.commit()
            with conn.cursor() as cur:
                cur.execute(
                    "SELECT raw_rows, clean_rows, last_raw_date FROM bp_asset_data_status WHERE symbol=%s AND source=%s",
                    ("__T4_TEST__", "__t4__"),
                )
                row = cur.fetchone()
                assert row[0] == 0 and row[1] == 0 and row[2] is None
        finally:
            with conn.cursor() as cur:
                cur.execute(
                    "DELETE FROM bp_asset_data_status WHERE symbol=%s AND source=%s",
                    ("__T4_TEST__", "__t4__"),
                )
            conn.commit()


# ---------------------------------------------------------------------
# list_assets / list_admin_assets 透出 currency
# ---------------------------------------------------------------------
def test_list_assets_returns_currency():
    from bp_api.repositories import list_assets

    with _mock_conn() as (conn, cur):
        cur.fetchone.return_value = (date(2026, 9, 4),)  # _stale_frontier 前沿日
        cur.fetchall.return_value = [
            # symbol, source, category, name, asset_class, vendor, adjust,
            # logical_source, last_clean_date, currency, lag_trading_days
            ("513500", "etf_em", "etf", "标普500ETF", "equity", "东财", "hfq",
             "etf_em", date(2026, 9, 4), "USD", 0),
            ("510300", "etf_em", "etf", "沪深300ETF", "equity", "东财", "hfq",
             "etf_em", date(2026, 9, 4), "CNY", 3),
        ]
        out = list_assets(conn)
    sql = " ".join(cur.execute.call_args[0][0].split())
    assert "c.currency" in sql
    assert "bp_trading_calendar" in sql  # 落后交易日数来自 A 股交易日历
    by_symbol = {a["symbol"]: a for a in out}
    assert by_symbol["513500"]["currency"] == "USD"
    assert by_symbol["510300"]["currency"] == "CNY"
    # 滞后语义: 落后 >= 2 个交易日才算「滞后」(差 1 日是正常增量节奏)
    assert by_symbol["513500"]["lag_trading_days"] == 0
    assert by_symbol["513500"]["is_lagging"] is False
    assert by_symbol["510300"]["lag_trading_days"] == 3
    assert by_symbol["510300"]["is_lagging"] is True


def test_list_assets_lagging_boundary():
    """边界: NULL(从未有清洗数据)/1 日/2 日 分别不滞后、不滞后、滞后。"""
    from bp_api.repositories import list_assets

    with _mock_conn() as (conn, cur):
        cur.fetchone.return_value = (date(2026, 9, 4),)
        cur.fetchall.return_value = [
            ("A", "s", None, "a", "equity", "v", None, "s", None, "CNY", None),
            ("B", "s", None, "b", "equity", "v", None, "s", date(2026, 9, 3), "CNY", 1),
            ("C", "s", None, "c", "equity", "v", None, "s", date(2026, 9, 2), "CNY", 2),
            ("D", "s", None, "d", "equity", "v", None, "s", date(2026, 9, 1), "CNY", 0),
        ]
        out = list_assets(conn)
    by = {a["symbol"]: a for a in out}
    assert by["A"]["lag_trading_days"] is None and by["A"]["is_lagging"] is False
    assert by["B"]["is_lagging"] is False  # 差 1 日: 正常
    assert by["C"]["is_lagging"] is True   # 差 2 日: 滞后
    assert by["D"]["is_lagging"] is False  # 每日都在跑


def test_list_admin_assets_returns_currency():
    from bp_api.repositories import list_admin_assets

    with _mock_conn() as (conn, cur):
        cur.fetchone.return_value = (date(2026, 9, 4),)  # _stale_frontier 前沿日
        cur.fetchall.return_value = [
            # symbol, source, category, name, start_date, is_deleted, asset_class, vendor,
            # last_raw_date, last_clean_date, raw_rows, clean_rows,
            # last_success_at, last_error, last_probe_ms, is_selectable, adjust,
            # logical_source, currency, lag_trading_days
            ("000300", "cn_index_em", "index", "沪深300", None, 0, "equity", "东财",
             date(2026, 9, 4), date(2026, 9, 4), 2200, 2190,
             None, None, None, True, None,
             "cn_index_em", "CNY", 0),
        ]
        out = list_admin_assets(conn)
    sql = " ".join(cur.execute.call_args[0][0].split())
    assert "c.currency" in sql
    assert "bp_trading_calendar" in sql
    assert out[0]["currency"] == "CNY"
    assert out[0]["raw_rows"] == 2200  # 既有字段不回归
    assert out[0]["lag_trading_days"] == 0
    assert out[0]["is_lagging"] is False


# ---------------------------------------------------------------------
# list_asset_portfolios: 按资产反查引用组合(删除/停用确认框用)
# ---------------------------------------------------------------------
def test_list_asset_portfolios_groups_by_key_and_dedups():
    """同一资产在组合里可能有多行(不同象限) → 组合名只应出现一次; 且按 symbol@source 分组。"""
    from bp_api.repositories import list_asset_portfolios

    with _mock_conn() as (conn, cur):
        cur.fetchall.return_value = [
            ("510300", "etf_em", 12, "多资产全天候", True),
            ("510300", "etf_em", 31, "高频调仓版", False),
            ("000300", "cn_index_em", 12, "多资产全天候", True),
        ]
        out = list_asset_portfolios(conn)
    sql = " ".join(cur.execute.call_args[0][0].split())
    assert "DISTINCT" in sql  # 同资产多象限行不得重复计数
    assert "bp_portfolio_asset" in sql
    by_key = {r["key"]: r["portfolios"] for r in out}
    assert set(by_key) == {"510300@etf_em", "000300@cn_index_em"}
    assert [p["portfolio_id"] for p in by_key["510300@etf_em"]] == [12, 31]
    assert by_key["510300@etf_em"][0]["is_demo"] is True
    assert by_key["000300@cn_index_em"][0]["name"] == "多资产全天候"


def test_list_asset_portfolios_empty():
    from bp_api.repositories import list_asset_portfolios

    with _mock_conn() as (conn, cur):
        cur.fetchall.return_value = []
        assert list_asset_portfolios(conn) == []


# ---------------------------------------------------------------------
# ingest 收尾: advanced 门控 → with_count=True 行数重算
# ---------------------------------------------------------------------
def test_sync_result_advanced_defaults_false():
    from bp_ingest.ingest import SyncResult

    r = SyncResult("510300", "etf_em", "ok")
    assert r.advanced is False


def test_ingest_run_recounts_only_advanced_assets():
    """run(refresh_clean=True) 收尾: 仅对 advanced=True 的资产做 with_count=True 刷新。"""
    from unittest.mock import patch

    from bp_ingest import ingest as ingest_mod

    results = [
        ingest_mod.SyncResult("510300", "etf_em", "ok", rows=2, advanced=True),
        ingest_mod.SyncResult("000300", "cn_index_em", "skip", rows=0, advanced=False),
    ]
    calls: list[tuple] = []
    refreshed: list[tuple] = []

    def _fake_refresh_asset_status(conn, symbol, source, *args, **kwargs):
        calls.append((symbol, source, kwargs.get("with_count")))

    def _fake_refresh_all(conn, **kwargs):
        refreshed.append(kwargs.get("with_count"))

    configs = [
        MagicMock(symbol="510300", source="etf_em"),
        MagicMock(symbol="000300", source="cn_index_em"),
    ]
    conn = MagicMock()
    with patch.object(ingest_mod.db, "fetch_active_configs", return_value=configs), \
         patch.object(ingest_mod.db, "connect", return_value=_fake_conn_ctx(conn)), \
         patch.object(ingest_mod, "_sync_one", side_effect=lambda conn, cfg, *a, **k: next(
             r for r in results if r.symbol == cfg.symbol
         )), \
         patch.object(ingest_mod, "_polite_sleep", lambda app: None), \
         patch.object(ingest_mod, "TradingCalendar", lambda: MagicMock(load=lambda: None)), \
         patch("bp_api.repositories.refresh_asset_status", _fake_refresh_asset_status), \
         patch("bp_api.quant.cleaning.rebuild_clean", lambda *a, **k: 0), \
         patch("bp_api.daily_update.refresh_all_asset_status", _fake_refresh_all), \
         patch("bp_api.daily_update.enqueue_ready_portfolios", lambda conn: []), \
         patch.object(ingest_mod, "_log_summary", lambda r: None):
        ingest_mod.run(MagicMock(), symbols=None, refresh_clean=True)

    # 推进的资产 → with_count=True 单独重算; 未推进的只由 refresh_all(默认 False) 走 MAX
    assert ("510300", "etf_em", True) in calls
    assert not any(c[0] == "000300" and c[2] is True for c in calls)
    assert refreshed == [None]  # ingest 收尾用默认 with_count=False(仅 MAX)


class _fake_conn_ctx:
    def __init__(self, conn):
        self._conn = conn

    def __enter__(self):
        return self._conn

    def __exit__(self, *exc):
        return False
