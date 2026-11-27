"""估值最新快照 / MVI overlay / 跟踪基金 meta 的仓储集成测试（真实 bp_mig_test）。

依赖 ddl/80 已应用（bp_index_valuation_latest）；不可达时整文件 skip。
测试数据统一 T80 前缀并在前后清理，避免污染同一测试库上的其他并行任务。
"""

from __future__ import annotations

from datetime import date, timedelta
from types import SimpleNamespace

import psycopg
import pytest

from bp_api import repositories_valuation as repo
from bp_api.tests._mig_db import connect_mig_test
from bp_ingest.db import QuoteRow, upsert_quotes

PREFIX = "T80"


def _connect() -> psycopg.Connection:
    # P1-4：显式 BP_MIG_TEST_DSN / BP_MIG_TEST=1 才连接；不硬编码 host、不读 .env
    return connect_mig_test()


def _purge(conn: psycopg.Connection) -> None:
    with conn.cursor() as cur:
        cur.execute("DELETE FROM bp_index_master WHERE index_code LIKE %s", (PREFIX + "%",))
        cur.execute("DELETE FROM bp_index_quote_daily WHERE position('T80' in symbol) > 0")
        cur.execute("DELETE FROM bp_index_quote_health WHERE position('T80' in symbol) > 0")
        cur.execute("DELETE FROM bp_fund_master WHERE fund_code LIKE %s", (PREFIX + "%",))
        cur.execute("DELETE FROM bp_fund_risk WHERE fund_code LIKE %s", (PREFIX + "%",))
        cur.execute("DELETE FROM bp_market_valuation_index WHERE as_of >= DATE '2099-01-01'")
    conn.commit()


@pytest.fixture(scope="module")
def conn():
    connection = _connect()
    _purge(connection)
    yield connection
    connection.rollback()
    _purge(connection)
    connection.close()


@pytest.fixture(autouse=True)
def _clean(conn):
    conn.rollback()
    _purge(conn)
    yield
    conn.rollback()
    _purge(conn)


def _seed_master(conn, codes: list[str]) -> None:
    repo.upsert_index_master(
        conn,
        [
            {
                "index_code": code,
                "market": "CSI",
                "wind_code": f"{code}.CSI",
                "name": f"Test {code}",
                "index_type": "宽基",
                "publisher": "测试编制方",
                "is_active": True,
                "is_tracked": True,
            }
            for code in codes
        ],
    )


def _seed_valuation(conn, code: str, base: date, days: int = 10) -> None:
    for offset in range(days):
        trade_date = base - timedelta(days=offset)
        repo.upsert_valuation_daily(
            conn,
            [
                {
                    "index_code": code,
                    "trade_date": trade_date,
                    "calc_src": "pingan_index",
                    "pe_ttm": 20.0 + offset,
                    "pb": 2.0 + offset * 0.01,
                    "dividend_yield_ttm": 3.0,
                    "erp": 1.5,
                    "roe_ttm": 11.0 + offset * 0.1,
                    "is_primary": True,
                    "raw": {"etf_fund": []},
                }
            ],
        )
    # 周频历史：一年，用于 coverage_start 与 sparkline
    for week in range(60):
        trade_date = base - timedelta(days=7 * week)
        for metric, value in (
            ("pe_ttm", 20.0 + week * 0.1),
            ("pb", 2.0 + week * 0.01),
            ("dividend_yield_ttm", 3.0),
            ("erp", 1.5),
        ):
            repo.upsert_valuation_series(
                conn,
                [
                    {
                        "index_code": code,
                        "trade_date": trade_date,
                        "metric": metric,
                        "calc_src": "pingan_index",
                        "value": value,
                        "is_weekly": True,
                    }
                ],
            )


def _seed_percentiles(conn, code: str, base: date) -> None:
    rows = []
    for metric_index, metric in enumerate(
        ("pe_ttm", "pb", "dividend_yield_ttm", "erp")
    ):
        for window_index, window in enumerate(("1y", "3y", "5y", "10y", "all")):
            rows.append(
                {
                    "index_code": code,
                    "as_of_date": base,
                    "metric": metric,
                    "window_key": window,
                    "calc_src": "pingan_index",
                    "pct": 40.0 + metric_index * 2 + window_index,
                    "sample_size": 200,
                }
            )
    repo.upsert_percentiles(conn, rows)


def _seed_quotes(conn, code: str, base: date, count: int = 400) -> None:
    rows = []
    for offset in range(count):
        trade_date = base - timedelta(days=offset)
        if trade_date.weekday() >= 5:
            continue
        rows.append(
            QuoteRow(
                trade_date=trade_date,
                symbol=code,
                source="cn_index_em",
                category="index",
                name=code,
                open=None,
                high=None,
                low=None,
                close=4000.0 + offset,
                volume=None,
                amount=None,
                turnover_rate=None,
                pct_change=None,
                adjust="bfq",
            )
        )
    upsert_quotes(conn, rows)


def test_refresh_and_read_snapshot(conn):
    base = date(2026, 11, 27)
    codes = [f"{PREFIX}001", f"{PREFIX}002"]
    _seed_master(conn, codes)
    for code in codes:
        _seed_valuation(conn, code, base)
        _seed_percentiles(conn, code, base)
        _seed_quotes(conn, code, base)
    with conn.cursor() as cur:
        cur.execute(
            "INSERT INTO bp_index_fund_scale (index_code, fund_count, aum_sum, as_of)"
            " VALUES (%s, 3, 123456.0, %s) ON CONFLICT (index_code) DO UPDATE SET"
            " fund_count = EXCLUDED.fund_count, aum_sum = EXCLUDED.aum_sum",
            (codes[0], base),
        )
        cur.execute(
            "INSERT INTO bp_index_quote_health"
            " (symbol, last_trade_date, expected_trade_date, lag_trading_days,"
            "  has_quote, status)"
            " VALUES (%s, %s, %s, 0, TRUE, 'ok')"
            " ON CONFLICT (symbol) DO UPDATE SET status = 'ok'",
            (codes[0], base, base),
        )
    conn.commit()

    written = repo.refresh_valuation_latest(conn, index_codes=codes)
    conn.commit()
    assert written == 2

    rows = repo.get_valuation_latest_list(conn, window="5y")
    rows = [row for row in rows if row["index_code"].startswith(PREFIX)]
    assert len(rows) == 2
    first = next(row for row in rows if row["index_code"] == codes[0])
    assert first["pe_ttm"] == pytest.approx(20.0)
    assert first["pe_percentile"] == pytest.approx(42.0)  # 5y 窗口：40 + metric*2 + window_idx
    assert first["pb_percentile"] == pytest.approx(44.0)
    assert first["has_valuation"] is True
    assert first["fund_count"] == 3
    assert first["fund_aum"] == pytest.approx(123456.0)
    assert first["quote_status"] == "ok"
    # ddl/81：ROE(TTM) 随快照返回，ROE×PE 矩阵数据源（不造数，缺失为 None）。
    assert first["roe_ttm"] == pytest.approx(11.0)
    assert first["close_price"] == pytest.approx(4000.0)
    assert first["change_pct"] == pytest.approx((4000.0 / 4001.0 - 1) * 100, abs=1e-6)
    assert first["coverage_start"] is not None
    assert first["updated_at"] is not None
    # 3y 窗口分位按窗口取
    rows_3y = repo.get_valuation_latest_list(conn, window="3y")
    first_3y = next(row for row in rows_3y if row["index_code"] == codes[0])
    assert first_3y["pe_percentile"] == pytest.approx(41.0)

    with conn.cursor() as cur:
        cur.execute(
            "SELECT percentiles, pe_spark, coverage_start, price_trade_date,"
            " change_52w_pct FROM bp_index_valuation_latest WHERE index_code = %s",
            (codes[0],),
        )
        percentiles, spark, coverage_start, price_trade_date, change_52w = cur.fetchone()
    assert set(percentiles["pe_ttm"].keys()) == {"1y", "3y", "5y", "10y", "all"}
    assert set(spark.keys()) == {"pe_ttm", "pb", "dividend_yield_ttm", "erp"}
    assert 1 <= len(spark["pe_ttm"]) <= 60
    assert coverage_start is not None and coverage_start < base
    assert price_trade_date == base
    assert change_52w is not None


def test_tracker_funds_meta_and_row_fields(conn):
    index_code = f"{PREFIX}IDX"
    fund_a, fund_b = f"{PREFIX}F1", f"{PREFIX}F2"
    _seed_master(conn, [index_code])
    with conn.cursor() as cur:
        cur.execute(
            "INSERT INTO bp_fund_master (fund_code, name) VALUES (%s, '基金A'), (%s, '基金B')"
            " ON CONFLICT (fund_code) DO UPDATE SET name = EXCLUDED.name",
            (fund_a, fund_b),
        )
        cur.execute(
            "INSERT INTO bp_index_tracker_fund"
            " (index_code, fund_code, trade_date, aum, source, captured_at)"
            " VALUES"
            " (%(idx)s, %(fa)s, DATE '2026-11-21', 100.0, 'pingan_index',"
            "  TIMESTAMPTZ '2026-11-25 10:00:00+08'),"
            " (%(idx)s, %(fa)s, DATE '2026-11-23', 110.0, 'pingan_index',"
            "  TIMESTAMPTZ '2026-11-27 21:10:00+08'),"
            " (%(idx)s, %(fb)s, DATE '2026-11-23', 90.0, 'pingan_index',"
            "  TIMESTAMPTZ '2026-11-27 21:10:00+08')"
            " ON CONFLICT (index_code, fund_code, trade_date) DO UPDATE SET"
            "  aum = EXCLUDED.aum, captured_at = EXCLUDED.captured_at",
            {"idx": index_code, "fa": fund_a, "fb": fund_b},
        )
        cur.execute(
            "INSERT INTO bp_fund_risk"
            " (fund_code, as_of, tracking_error_1y, updated_at)"
            " VALUES (%s, DATE '2026-11-23', 4.31,"
            "  TIMESTAMPTZ '2026-11-27 21:15:00+08')"
            " ON CONFLICT (fund_code) DO UPDATE SET"
            "  as_of = EXCLUDED.as_of, tracking_error_1y = EXCLUDED.tracking_error_1y,"
            "  updated_at = EXCLUDED.updated_at",
            (fund_a,),
        )
    conn.commit()

    funds = repo.get_index_tracker_funds(conn, index_code)
    assert len(funds) == 2
    for row in funds:
        assert row["data_as_of"] == date(2026, 11, 23)
        assert row["updated_at"] is not None
    fund_a_row = next(row for row in funds if row["fund_code"] == fund_a)
    assert fund_a_row["tracking_error_1y"] == pytest.approx(4.31)
    assert fund_a_row["risk_updated_at"] is not None

    meta = repo.get_index_tracker_funds_meta(conn, index_code)
    assert meta["data_as_of"] == date(2026, 11, 23)
    assert meta["updated_at"] is not None
    assert meta["risk_updated_at"] is not None
    assert meta["fund_count"] == 2


def test_price_series_dedupes_multiple_sources(conn):
    code = f"{PREFIX}Q"
    _seed_master(conn, [code])
    upsert_quotes(
        conn,
        [
            QuoteRow(
                trade_date=date(2026, 11, 25),
                symbol=code,
                source="cn_index_em",
                category="index",
                name=code,
                open=None,
                high=None,
                low=None,
                close=100.0,
                volume=None,
                amount=None,
                turnover_rate=None,
                pct_change=None,
                adjust="bfq",
            ),
            QuoteRow(
                trade_date=date(2026, 11, 25),
                symbol=code,
                source="csindex_perf",
                category="index",
                name=code,
                open=None,
                high=None,
                low=None,
                close=101.0,
                volume=None,
                amount=None,
                turnover_rate=None,
                pct_change=None,
                adjust="bfq",
            ),
            QuoteRow(
                trade_date=date(2026, 11, 26),
                symbol=code,
                source="cn_index_em",
                category="index",
                name=code,
                open=None,
                high=None,
                low=None,
                close=102.0,
                volume=None,
                amount=None,
                turnover_rate=None,
                pct_change=None,
                adjust="bfq",
            ),
        ],
    )
    with conn.cursor() as cur:
        cur.execute(
            "UPDATE bp_index_quote_daily SET updated_at ="
            "  TIMESTAMPTZ '2026-11-26 09:00:00+08'"
            " WHERE symbol = %s AND trade_date = DATE '2026-11-25'"
            "   AND source = 'cn_index_em'",
            (code,),
        )
        cur.execute(
            "UPDATE bp_index_quote_daily SET updated_at ="
            "  TIMESTAMPTZ '2026-11-27 09:00:00+08'"
            " WHERE symbol = %s AND trade_date = DATE '2026-11-25'"
            "   AND source = 'csindex_perf'",
            (code,),
        )
    conn.commit()

    series = repo.get_index_price_series(conn, code, years=2)
    assert [item["trade_date"] for item in series] == [
        date(2026, 11, 25),
        date(2026, 11, 26),
    ]
    # 同 (symbol, date) 取最新更新的一行（csindex_perf 更晚 -> 101）
    assert series[0]["close"] == pytest.approx(101.0)


def test_mvi_range_replace_and_overlay(conn):
    code = f"{PREFIX}OVL"
    _seed_master(conn, [code])
    rows = [
        {
            "as_of": date(2099, 1, 2) + timedelta(days=7 * offset),
            "mvi": 50.0 + offset,
            "cheap_score": 50.0 - offset,
            "risk_score": 40.0 + offset,
            "zone": "合理",
            "factors": {"a": 1.0},
            "weights": {"a": 1.0},
            "contributions": {"a": 1.0},
            "risk_factors": {"波动率分位": 40.0, "回撤分位": 40.0},
        }
        for offset in range(6)
    ]
    # P1-4：replace 会先 DELETE 整表再写入——测试内不 commit，结束 rollback，
    # 共享测试库的真实 MVI 历史不受影响（也不做无 WHERE 的整表 DELETE）。
    repo.replace_market_valuation_index(conn, rows)
    try:
        data = repo.get_market_valuation_index_range(conn, range_key="all")
        assert data["latest"]["as_of"] == "2099-02-06"
        assert len(data["history"]) >= 6
        assert data["history"][-1]["mvi"] == pytest.approx(55.0)

        # overlay：指数行情缺失 -> missing + reason，不造数
        overlay = repo.get_market_mvi_overlay(conn, code, range_key="all")
        assert overlay["missing"] is True
        assert overlay["reason"] == "no_price_data_for_overlay"
        assert overlay["series"] == []
        assert len(overlay["mvi"]) >= 6

        # 补上行情后 -> 返回价格序列（窗口从 MVI 起点开始）
        quotes = []
        for offset in range(10):
            day = date(2099, 1, 2) + timedelta(days=offset)
            if day.weekday() >= 5:
                continue
            quotes.append(
                QuoteRow(
                    trade_date=day,
                    symbol=code,
                    source="cn_index_em",
                    category="index",
                    name=code,
                    open=None,
                    high=None,
                    low=None,
                    close=5000.0 + offset,
                    volume=None,
                    amount=None,
                    turnover_rate=None,
                    pct_change=None,
                    adjust="bfq",
                )
            )
        upsert_quotes(conn, quotes)
        overlay = repo.get_market_mvi_overlay(conn, code, range_key="all")
        assert overlay["missing"] is False
        assert overlay["series"]
        assert overlay["coverage_start"] == date(2099, 1, 2)
        assert overlay["mvi_end"] == "2099-02-06"
    finally:
        # 只回滚本测试事务：replace 的整表 DELETE 与测试行情都随事务撤销
        conn.rollback()


def test_replace_market_valuation_index_deletes_stale_rows(conn):
    old_rows = [
        {
            "as_of": date(2099, 3, 5),
            "mvi": 10.0,
            "cheap_score": 90.0,
            "risk_score": 10.0,
            "zone": "极度低估",
            "factors": None,
            "weights": None,
            "contributions": None,
            "risk_factors": None,
        },
        {
            "as_of": date(2099, 3, 12),
            "mvi": 20.0,
            "cheap_score": 80.0,
            "risk_score": 20.0,
            "zone": "低估",
            "factors": None,
            "weights": None,
            "contributions": None,
            "risk_factors": None,
        },
    ]
    # P1-4：整表 replace 属于生产语义，测试内不 commit；finally rollback 撤销，
    # 不对共享库做无 WHERE 的整表 DELETE 持久化。
    repo.upsert_market_valuation_index(conn, old_rows)
    try:
        written = repo.replace_market_valuation_index(conn, [old_rows[0]])
        assert written == 1
        with conn.cursor() as cur:
            cur.execute(
                "SELECT as_of FROM bp_market_valuation_index"
                " WHERE as_of >= DATE '2099-01-01' ORDER BY as_of"
            )
            assert [row[0] for row in cur.fetchall()] == [date(2099, 3, 5)]
    finally:
        conn.rollback()

# ---------------------------------------------------------------------------
# 纯 mock：get_valuation_latest_list 缺失窗口分位必须置 None（P2）
# ---------------------------------------------------------------------------
class _ListCursor:
    def __init__(self, conn: "_ListConn") -> None:
        self.conn = conn

    def execute(self, sql: str, params: object = None) -> None:
        self.conn.sql = sql

    def fetchall(self) -> list:
        return list(self.conn.rows)

    @property
    def description(self) -> list:
        return [SimpleNamespace(name=name) for name in self.conn.columns]

    def __enter__(self):
        return self

    def __exit__(self, *exc: object) -> bool:
        return False


class _ListConn:
    def __init__(self, rows: list, columns: list[str]) -> None:
        self.rows = rows
        self.columns = columns
        self.sql = ""

    def cursor(self) -> _ListCursor:
        return _ListCursor(self)


_LIST_COLUMNS = [
    "index_code", "name", "short_name", "index_type", "industry", "market",
    "publisher", "trade_date", "calc_src", "is_primary", "pe_ttm", "pb",
    "dividend_yield_ttm", "erp", "roe_ttm", "pe_percentile", "pb_percentile",
    "dividend_percentile", "erp_percentile", "percentiles", "close_price",
    "change_pct", "change_52w_pct", "position_52w_pct", "price_trade_date",
    "coverage_start", "updated_at", "fund_count", "fund_aum", "quote_status",
    "quote_lag_days",
]


def _latest_row(index_code: str, percentiles: dict, *, pe_flat=99.0, pb_flat=88.0) -> tuple:
    values = {
        "index_code": index_code,
        "name": index_code,
        "short_name": None,
        "index_type": "宽基",
        "industry": None,
        "market": "SH",
        "publisher": "测试",
        "trade_date": date(2026, 11, 27),
        "calc_src": "pingan_index",
        "is_primary": True,
        "pe_ttm": 13.4,
        "pb": 1.38,
        "dividend_yield_ttm": 3.2,
        "erp": 5.1,
        "roe_ttm": 10.2,
        "pe_percentile": pe_flat,
        "pb_percentile": pb_flat,
        "dividend_percentile": None,
        "erp_percentile": None,
        "percentiles": percentiles,
        "close_price": 4010.5,
        "change_pct": 0.42,
        "change_52w_pct": 12.3,
        "position_52w_pct": 74.5,
        "price_trade_date": date(2026, 11, 27),
        "coverage_start": date(2021, 11, 19),
        "updated_at": None,
        "fund_count": 1,
        "fund_aum": 100.0,
        "quote_status": "ok",
        "quote_lag_days": 0,
    }
    return tuple(values[name] for name in _LIST_COLUMNS)


def test_get_valuation_latest_list_missing_window_percentile_is_none():
    """请求窗口的分位缺失时必须 None，不能回落 5y 扁平列（P2 假分位）。"""
    rows = [
        _latest_row(
            "T80P1",
            {"pe_ttm": {"5y": 42.0}, "pb": {"3y": 44.0}},
        ),
        _latest_row("T80P2", {}),
    ]
    conn = _ListConn(rows, _LIST_COLUMNS)

    by_window = {
        row["window"]: row
        for row in repo.get_valuation_latest_list(conn, window="3y")
    }
    assert len(by_window) == 2
    assert by_window["3y"]["pe_percentile"] is None  # 3y 缺失，不得用 5y 的 99
    assert by_window["3y"]["pb_percentile"] == pytest.approx(44.0)

    rows_5y = repo.get_valuation_latest_list(conn, window="5y")
    first_5y = next(row for row in rows_5y if row["index_code"] == "T80P1")
    second_5y = next(row for row in rows_5y if row["index_code"] == "T80P2")
    assert first_5y["pe_percentile"] == pytest.approx(42.0)  # JSONB 5y 优先
    assert first_5y["pb_percentile"] is None  # pb 无 5y -> None（不得回落扁平 88）
    assert second_5y["pe_percentile"] is None
    assert second_5y["pb_percentile"] is None
