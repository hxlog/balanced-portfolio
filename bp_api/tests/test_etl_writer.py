"""锚定/写入/覆盖快照测试（T7，打桩 psycopg）。"""
from __future__ import annotations

from datetime import date

import pytest

from bp_etl.adapters.base import Bar, NavRow
from bp_etl.anchors import NoOverlapError, overlap_ratio, reanchor
from bp_etl.registry import REGISTRY
from bp_etl.writer import fill_pct_change, refresh_coverage, write_bars, write_navs


def _bar(symbol: str, d: date, close: float, *, source: str = "tencent_kline",
         adjust: str = "hfq", pct: float | None = None) -> Bar:
    return Bar(
        symbol=symbol, trade_date=d, open=close - 1, high=close + 1,
        low=close - 2, close=close, volume=100, amount=None,
        pct_change=pct, source=source, adjust=adjust,
    )


class FakeCursor:
    def __init__(self, conn: "FakeConn") -> None:
        self.conn = conn

    def __enter__(self) -> "FakeCursor":
        return self

    def __exit__(self, *exc: object) -> None:
        return None

    def execute(self, sql: str, params: object = None) -> None:
        self.conn.queries.append((sql, params))
        if "SELECT close FROM" in sql:
            self.conn._fetchone = (
                (self.conn.prev_close,) if self.conn.prev_close is not None else None
            )
        elif "GROUP BY" in sql:
            self.conn._fetchall = self.conn.group_rows
        elif "SELECT" in sql:
            self.conn._fetchall = self.conn.group_rows

    def executemany(self, sql: str, payload: list) -> None:
        self.conn.executed.append((sql, list(payload)))

    def fetchone(self) -> object:
        return self.conn._fetchone

    def fetchall(self) -> list:
        return self.conn._fetchall


class FakeConn:
    def __init__(self, *, prev_close: float | None = None, group_rows: list | None = None) -> None:
        self.prev_close = prev_close
        self.group_rows = group_rows or []
        self.queries: list[tuple[str, object]] = []
        self.executed: list[tuple[str, list]] = []
        self._fetchone = None
        self._fetchall: list = []

    def cursor(self) -> FakeCursor:
        return FakeCursor(self)


D1 = date(2026, 11, 20)
D2 = date(2026, 11, 23)
A_STOCK = REGISTRY["a_stock"]
ETF = REGISTRY["etf"]
FUND = REGISTRY["fund_nav"]


def test_reanchor_scales_to_anchor_basis() -> None:
    anchor = [_bar("600036", D1, 100.0, source="sina_kline"), _bar("600036", D2, 101.0, source="sina_kline")]
    fallback = [_bar("600036", D1, 50.0, source="tencent_kline"), _bar("600036", D2, 50.5, source="tencent_kline")]
    assert overlap_ratio(anchor, fallback) == pytest.approx(2.0)
    anchored = reanchor(anchor, fallback)
    assert [b.close for b in anchored] == pytest.approx([100.0, 101.0])
    assert anchored[0].source == "tencent_kline:anchored"
    assert anchored[0].volume == 100


def test_reanchor_without_overlap_raises() -> None:
    anchor = [_bar("600036", D1, 100.0)]
    fallback = [_bar("600036", D2, 50.0)]
    with pytest.raises(NoOverlapError):
        reanchor(anchor, fallback)


def test_fill_pct_change_uses_prev_close_and_batch_chain() -> None:
    conn = FakeConn(prev_close=10.0)
    bars = [_bar("600036", D1, 11.0), _bar("600036", D2, 12.1)]
    filled = fill_pct_change(conn, A_STOCK, bars)
    assert filled[0].pct_change == pytest.approx(10.0)
    assert filled[1].pct_change == pytest.approx(10.0)
    assert any("SELECT close FROM bp_stock_quote_daily" in sql and "source = %s" in sql for sql, _ in conn.queries)


def test_fill_pct_change_keeps_source_pct() -> None:
    conn = FakeConn(prev_close=10.0)
    bars = [_bar("600036", D1, 11.0, pct=9.9), _bar("600036", D2, 12.1, pct=10.0)]
    filled = fill_pct_change(conn, A_STOCK, bars)
    assert [b.pct_change for b in filled] == [9.9, 10.0]
    assert conn.queries == []  # 源已提供 pct，不查库


def test_write_bars_payload_and_sql() -> None:
    conn = FakeConn(prev_close=None)
    n = write_bars(conn, ETF, [_bar("510300", D2, 4.05, source="tencent_qt", adjust="bfq")])
    assert n == 1
    sql, payload = conn.executed[0]
    assert "ON CONFLICT (etf_code, trade_date, source, adjust)" in sql
    assert payload[0]["key"] == "510300"
    assert payload[0]["adjust"] == "bfq"


def test_write_navs() -> None:
    conn = FakeConn()
    n = write_navs(conn, [NavRow("110011", D2, 1.234, 3.456, "em_rankhandler")])
    assert n == 1
    sql, payload = conn.executed[0]
    assert "ON CONFLICT (fund_code, trade_date)" in sql
    assert payload[0] == ("110011", D2, 1.234, 3.456, "em_rankhandler")


def test_refresh_coverage_incremental_bar() -> None:
    conn = FakeConn(group_rows=[("600036", "hfq", D2), ("600036", "bfq", D2)])
    n = refresh_coverage(conn, A_STOCK, ["600036"])
    assert n == 2
    sql, payload = conn.executed[0]
    assert "ON CONFLICT (kind, code, adjust)" in sql
    assert ("stock", "600036", "hfq", D2) in payload
    assert any("GROUP BY" in q for q, _ in conn.queries)


def test_refresh_coverage_nav() -> None:
    conn = FakeConn(group_rows=[("110011", "", D2)])
    n = refresh_coverage(conn, FUND, ["110011"])
    assert n == 1
    _, payload = conn.executed[0]
    assert payload[0] == ("fund", "110011", "", D2)

def test_write_bars_index_table() -> None:
    from bp_etl.adapters.base import Bar
    from bp_etl.registry import REGISTRY
    from bp_etl.writer import write_bars as write_bars_fn

    conn = FakeConn(prev_close=None)
    spec = REGISTRY["legacy_index"]
    bar = Bar(symbol="000300", trade_date=D2, open=4000.0, high=4010.0, low=3990.0,
              close=4005.0, volume=100, amount=1000.0, pct_change=0.1,
              source="cn_index_em", adjust="bfq")
    n = write_bars_fn(conn, spec, [bar])
    assert n == 1
    sql, payload = conn.executed[0]
    assert "INSERT INTO bp_index_quote_daily" in sql
    assert "ON CONFLICT (symbol, source, adjust, trade_date)" in sql
    assert payload[0]["source"] == "cn_index_em" and payload[0]["key"] == "000300"