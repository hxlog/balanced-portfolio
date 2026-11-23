"""四类 dataset runner + CLI 测试（T10，离线 fixture）。"""
from __future__ import annotations

from datetime import date

import pytest

import bp_etl.adapters.eastmoney as em
import bp_etl.adapters.sina as sina
import bp_etl.adapters.tencent as tencent
from bp_etl.adapters.base import Bar, NavRow
from bp_etl.datasets import get_runners
from bp_etl.datasets.a_stock import AStockRunner
from bp_etl.datasets.etf import ETFRunner
from bp_etl.datasets.fund_nav import FundNavRunner
from bp_etl.datasets.hk_stock import HKStockRunner
from bp_etl.cli import build_parser

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

    def fetchall(self) -> list:
        return self.conn.rows

    def fetchone(self) -> object:
        return self.conn.one


class FakeConn:
    def __init__(self, rows: list | None = None, one: object = None) -> None:
        self.rows = rows or []
        self.one = one
        self.queries: list[tuple[str, object]] = []

    def cursor(self) -> FakeCursor:
        return FakeCursor(self)


class FakeChannel:
    def __init__(self, kind: str = "direct") -> None:
        self.channel_kind = kind

    def throttle(self) -> float:
        return 0.0

    def get(self, url: str, **kw: object) -> object:
        raise AssertionError("adapter 已被打桩，不应真实请求")


class FakeManager:
    def __init__(self, kind: str = "direct") -> None:
        self.kind = kind
        self.spawned: list[str] = []
        self.got: list[str] = []

    def get(self, source: str) -> FakeChannel:
        self.got.append(source)
        return FakeChannel(self.kind)

    def spawn(self, source: str) -> FakeChannel:
        self.spawned.append(source)
        return FakeChannel(self.kind)


def _bar(symbol: str, d: date = D2, close: float = 10.0, adjust: str = "bfq") -> Bar:
    return Bar(symbol=symbol, trade_date=d, open=close - 1, high=close + 1,
               low=close - 2, close=close, volume=100, source="x", adjust=adjust)


def test_get_runners_registers_four_datasets() -> None:
    runners = get_runners()
    assert set(runners) == {"a_stock", "hk_stock", "etf", "fund_nav"}
    for runner in runners.values():
        assert runner.spec.name in runners


def test_a_stock_runner_bfq(monkeypatch: pytest.MonkeyPatch) -> None:
    conn = FakeConn(rows=[("600036",), ("000001",)])
    monkeypatch.setattr(tencent, "fetch_qt_batch", lambda channel, codes: [_bar(c) for c in codes])
    bars = AStockRunner().fetch("bfq", ["600036", "000001"], D2, FakeManager())
    assert [b.symbol for b in bars] == ["600036", "000001"]


def test_a_stock_runner_hfq_uses_sina_factor(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(tencent, "fetch_qt_batch", lambda channel, codes: [_bar("600036", close=10.0)])
    monkeypatch.setattr(sina, "fetch_hfq_factor", lambda channel, symbol: [(date(2020, 1, 1), 2.0)])
    bars = AStockRunner().fetch("hfq", ["600036"], D2, FakeManager())
    assert len(bars) == 1
    assert bars[0].adjust == "hfq"
    assert bars[0].close == pytest.approx(20.0)


def test_hk_runner_bfq_parallel(monkeypatch: pytest.MonkeyPatch) -> None:
    def fake_fetch(channel: object, code: str, start: date, end: date) -> list[Bar]:
        return [_bar(code)]

    monkeypatch.setattr(sina, "fetch_hk_bfq", fake_fetch)
    manager = FakeManager()
    bars = HKStockRunner().fetch("bfq", ["00700", "09988"], D2, manager)
    assert {b.symbol for b in bars} == {"00700", "09988"}
    assert manager.spawned and all(source == "sina_hk_kline" for source in manager.spawned)


def test_hk_runner_hfq_em_fallback(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(tencent, "fetch_kline", lambda *a, **kw: [])
    called: list[str] = []

    def fake_em(channel: object, code: str, adjust: str, start: date, end: date, **kw: object) -> list[Bar]:
        called.append(code)
        return [_bar(code, adjust="hfq")]

    monkeypatch.setattr(em, "fetch_kline", fake_em)
    manager = FakeManager(kind="relay_sg")
    bars = HKStockRunner().fetch("hfq", ["00700"], D2, manager)
    assert bars and bars[0].adjust == "hfq"
    assert called == ["00700"]
    assert "em_kline" in manager.got


def test_etf_runner_bfq(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(tencent, "fetch_qt_batch", lambda channel, codes: [_bar(c) for c in codes])
    bars = ETFRunner().fetch("bfq", ["510300"], D2, FakeManager())
    assert bars[0].symbol == "510300"


def test_fund_nav_runner_expected_count() -> None:
    conn = FakeConn(one=(25000,))
    assert FundNavRunner().expected_count(conn, D2) == 25000


def test_fund_nav_runner_rank_plus_gap_fill(monkeypatch: pytest.MonkeyPatch) -> None:
    def fake_rank(channel: object, page: int = 1, **kw: object):
        if page == 1:
            return [NavRow("000001", D2, 1.1, None, "em_rankhandler")], 2
        return [NavRow("000003", D2, 1.2, None, "em_rankhandler")], 2

    def fake_lsjz(channel: object, code: str, **kw: object) -> list[NavRow]:
        return [NavRow(code, D2, 2.0, None, "em_lsjz")]

    monkeypatch.setattr(em, "fetch_rankhandler", fake_rank)
    monkeypatch.setattr(em, "fetch_lsjz", fake_lsjz)
    rows = FundNavRunner().fetch("nav", ["000001", "000002", "000003"], D2, FakeManager())
    codes = {row.fund_code for row in rows}
    assert {"000001", "000002", "000003"} <= codes


def test_cli_parser_run_args() -> None:
    parser = build_parser()
    args = parser.parse_args(["run", "--dataset", "a_stock", "--adjust", "hfq", "--waves", "2", "--json"])
    assert args.command == "run"
    assert args.dataset == "a_stock" and args.adjust == "hfq" and args.waves == 2
    args2 = parser.parse_args(["service"])
    assert args2.command == "service"
