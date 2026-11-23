"""重建/校验测试（T11，离线 fixture）。"""
from __future__ import annotations

from datetime import date

import pytest

import bp_etl.rebuild as rebuild_mod
import bp_etl.writer as writer_mod
from bp_etl import adapters
from bp_etl.adapters.base import Bar
from bp_etl.cli import build_parser
from bp_etl.rebuild import (
    consolidate_sources,
    delete_other_sources,
    read_bfq_history,
    rebuild_a_stock_hfq,
)
from bp_etl.registry import REGISTRY
from bp_etl.verify import ratio_drift_stats

D1 = date(2026, 11, 20)
D2 = date(2026, 11, 23)


class FakeCursor:
    def __init__(self, conn: "FakeConn") -> None:
        self.conn = conn

    def __enter__(self) -> "FakeCursor":
        return self

    def __exit__(self, *exc: object) -> None:
        return None

    def execute(self, sql: str, params: object = None) -> None:
        self.conn.queries.append((sql, params))
        if self.conn.rows is not None and "SELECT" in sql:
            self.conn._rows = self.conn.rows

    def executemany(self, sql: str, payload: list) -> None:
        self.conn.executed.append((sql, list(payload)))

    def fetchall(self) -> list:
        return self.conn._rows

    def fetchone(self) -> object:
        return self.conn.one

    rowcount = 7


class FakeConn:
    def __init__(self, rows: list | None = None, one: object = None) -> None:
        self.rows = rows
        self.one = one
        self._rows: list = []
        self.queries: list[tuple[str, object]] = []
        self.executed: list[tuple[str, list]] = []
        self.commits = 0

    def cursor(self) -> FakeCursor:
        return FakeCursor(self)

    def commit(self) -> None:
        self.commits += 1


class FakeManager:
    def get(self, source: str) -> object:
        return object()


def test_read_bfq_history() -> None:
    conn = FakeConn(rows=[
        (D1, 10.0, 11.0, 9.0, 10.5, 100, 1050.0),
        (D2, 10.5, 12.0, 10.0, 11.0, 200, 2200.0),
    ])
    bars = read_bfq_history(conn, REGISTRY["a_stock"], "600036", date(2026, 1, 1))
    assert [b.trade_date for b in bars] == [D1, D2]
    assert bars[1].close == pytest.approx(11.0)
    assert bars[1].volume == 200
    sql, params = conn.queries[0]
    assert "DISTINCT ON (trade_date)" in sql
    assert "CASE source WHEN 'tencent_qt' THEN 0" in sql
    assert params == ("600036", date(2026, 1, 1))


def test_delete_other_sources(monkeypatch: pytest.MonkeyPatch) -> None:
    conn = FakeConn()
    deleted = delete_other_sources(conn, REGISTRY["a_stock"], "hfq", "sina_kline", symbols=["600036"])
    sql, params = conn.queries[0]
    assert "DELETE FROM bp_stock_quote_daily" in sql
    assert params == ["hfq", "sina_kline", ["600036"]]
    assert deleted == 7


def test_rebuild_a_stock_hfq(monkeypatch: pytest.MonkeyPatch) -> None:
    conn = FakeConn(rows=[("600036",), ("600037",)])

    def fake_read(conn_: object, spec: object, symbol: str, since: date) -> list[Bar]:
        if symbol != "600036":
            return []
        return [
            Bar(
                symbol="600036", trade_date=D1, open=9.0, high=11.0, low=8.0,
                close=10.0, volume=100, amount=None, source="rebuild_bfq", adjust="bfq",
            )
        ]

    monkeypatch.setattr(rebuild_mod, "read_bfq_history", fake_read)
    monkeypatch.setattr(rebuild_mod, "_max_date", lambda *a, **kw: None)
    monkeypatch.setattr(rebuild_mod, "_existing_hfq_dates", lambda *a, **kw: set())
    monkeypatch.setattr(adapters.sina, "fetch_hfq_factor", lambda ch, sym: [(date(2020, 1, 1), 2.0)])
    monkeypatch.setattr(adapters.sina, "build_hfq_from_bfq", lambda bars, factors: [
        Bar(symbol=b.symbol, trade_date=b.trade_date, open=b.open, high=b.high,
            low=b.low, close=b.close * 2, volume=b.volume, amount=None,
            source="sina_kline", adjust="hfq")
        for b in bars
    ])
    written: list[int] = []
    monkeypatch.setattr(writer_mod, "write_bars", lambda conn_, spec, rows: written.append(len(rows)) or len(rows))
    report = rebuild_a_stock_hfq(conn, FakeManager(), since=date(2020, 1, 1))
    assert report.symbols == 1 and report.skipped == 1 and report.written == 1
    assert report.deleted_legacy == 7
    assert written == [1]
    assert conn.commits == 1


def test_consolidate_sources() -> None:
    conn = FakeConn()
    report = consolidate_sources(conn, REGISTRY["hk_stock"], "hfq", "tencent_hk_kline")
    assert report.deleted_legacy == 7
    assert conn.commits == 1
    sql, params = conn.queries[0]
    assert "DELETE FROM bp_stock_quote_daily" in sql and params[0] == "hfq"


def test_ratio_drift_stats() -> None:
    ok = ratio_drift_stats([20.0, 20.0, 20.0, 20.0])
    assert ok["ok"] and ok["drift_count"] == 0
    drift = ratio_drift_stats([20.0, 20.0, 21.0, 21.0])
    assert drift["drift_count"] == 1 and drift["drift_ratio"] == pytest.approx(1 / 3, rel=1e-3)
    empty = ratio_drift_stats([])
    assert empty["ok"] and empty["points"] == 0


def test_cli_has_rebuild_and_verify() -> None:
    parser = build_parser()
    args = parser.parse_args(["rebuild", "--dataset", "all", "--limit", "5", "--json"])
    assert args.command == "rebuild" and args.limit == 5
    args2 = parser.parse_args(["verify", "--sample", "50", "--out", "x.json"])
    assert args2.command == "verify" and args2.sample == 50

def test_rebuild_delta_mode_writes_only_missing_dates(monkeypatch: pytest.MonkeyPatch) -> None:
    conn = FakeConn(rows=[("600036",)])
    bfq = [
        Bar(symbol="600036", trade_date=D1, open=9.0, high=11.0, low=8.0, close=10.0,
            volume=100, amount=None, source="rebuild_bfq", adjust="bfq"),
        Bar(symbol="600036", trade_date=D2, open=10.0, high=12.0, low=9.0, close=11.0,
            volume=100, amount=None, source="rebuild_bfq", adjust="bfq"),
    ]
    monkeypatch.setattr(rebuild_mod, "read_bfq_history", lambda *a, **kw: bfq)
    monkeypatch.setattr(rebuild_mod, "_max_date", lambda *a, **kw: D1)
    monkeypatch.setattr(rebuild_mod, "_existing_hfq_dates", lambda *a, **kw: {D1})
    monkeypatch.setattr(adapters.sina, "fetch_hfq_factor", lambda ch, sym: [(date(2020, 1, 1), 1.0)])
    monkeypatch.setattr(adapters.sina, "build_hfq_from_bfq", lambda bars, factors: [
        Bar(symbol=b.symbol, trade_date=b.trade_date, open=b.open, high=b.high, low=b.low,
            close=b.close, volume=b.volume, amount=None, source="sina_kline", adjust="hfq")
        for b in bars
    ])
    written: list[list] = []
    monkeypatch.setattr(writer_mod, "write_bars", lambda conn_, spec, rows: written.append(list(rows)) or len(rows))
    report = rebuild_a_stock_hfq(conn, FakeManager(), since=date(2020, 1, 1), mode="delta")
    assert report.written == 1
    assert len(written[0]) == 1 and written[0][0].trade_date == D2
