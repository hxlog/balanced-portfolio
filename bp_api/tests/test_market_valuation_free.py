"""市场估值免费源替代 + 优雅降级（纯 mock，不触网）。"""
from __future__ import annotations

from datetime import date, datetime, timezone, timedelta
from types import SimpleNamespace

import pytest

from bp_ingest import market_valuation as mv

CN = timezone(timedelta(hours=8))
TARGET = date(2026, 11, 27)


def _sina_rows(main: int = 900, chinext: int = 300, star: int = 300, bse: int = 30) -> list[dict]:
    rows: list[dict] = []

    def add(prefix: str, code_prefix: str, count: int, pe: float, pb: float) -> None:
        for index in range(count):
            code = f"{code_prefix}{index:04d}"
            rows.append({"symbol": f"{prefix}{code}", "code": code,
                         "per": pe + index % 5, "pb": pb + index % 3})

    add("sh", "600", main // 2, 12.0, 1.4)
    add("sz", "000", main - main // 2, 14.0, 1.6)
    add("sz", "300", chinext, 30.0, 3.0)
    add("sh", "688", star, 45.0, 4.0)
    add("bj", "83", bse, 18.0, 2.0)
    return rows


class _FakeCursor:
    def __init__(self, conn: "_FakeConn") -> None:
        self.conn = conn

    def execute(self, sql: str, params: object = None) -> None:
        self.conn.statements.append((sql, params))

    def fetchone(self):
        return self.conn.rows.pop(0) if self.conn.rows else None

    def __enter__(self):
        return self

    def __exit__(self, *exc: object) -> bool:
        return False


class _FakeConn:
    def __init__(self, rows: list | None = None) -> None:
        self.rows = list(rows or [])
        self.statements: list = []
        self.commits = 0

    def cursor(self):
        return _FakeCursor(self)

    def commit(self) -> None:
        self.commits += 1


def test_classify_board() -> None:
    assert mv.classify_board("sh600000", "600000") == "main"
    assert mv.classify_board("sz000001", "000001") == "main"
    assert mv.classify_board("sz300750", "300750") == "chinext"
    assert mv.classify_board("sh688981", "688981") == "star"
    assert mv.classify_board("bj920000", "920000") == "bse"


def test_stats_from_sina_medians_positive_only() -> None:
    grouped = mv.stats_from_sina([
        {"symbol": "sh600000", "code": "600000", "per": 10, "pb": 1.0},
        {"symbol": "sh600001", "code": "600001", "per": 20, "pb": 2.0},
        {"symbol": "sh600002", "code": "600002", "per": -5, "pb": None},
    ])
    pe_med, pe_eq, pb_med, pb_eq, sample = mv._sina_stats(grouped["main"])
    assert sample == 2
    assert pe_med == pytest.approx(15.0)
    assert pe_eq == pytest.approx(15.0)
    assert pb_med == pytest.approx(1.5)
    assert len(grouped["all"]) == 3


def _wire(monkeypatch: pytest.MonkeyPatch) -> dict:
    written: dict = {}
    statuses: list = []

    def fake_write(conn, trade_date, payload, *, calc_src):
        written.update({"trade_date": trade_date, "payload": payload, "calc_src": calc_src})

    monkeypatch.setattr(mv, "_write_payload", fake_write)
    monkeypatch.setattr(
        mv, "_record_status",
        lambda conn, as_of, status, note, **kw: statuses.append(
            {"as_of": as_of, "status": status, "note": note, **kw}
        ),
    )
    return {"written": written, "statuses": statuses}


def test_compute_uses_sina_free_source(monkeypatch: pytest.MonkeyPatch) -> None:
    _wire(monkeypatch)
    summary = mv.compute(_FakeConn(), as_of=TARGET, now=datetime(2026, 11, 27, 21, 20, tzinfo=CN),
                         fetch_sina=lambda: _sina_rows())
    assert summary["status"] == "ok"
    assert summary["source"] == mv.CALC_SRC_SINA
    assert summary["as_of"] == TARGET.isoformat()
    assert summary["boards"]["all"] >= 1000


def test_compute_falls_back_to_eastmoney(monkeypatch: pytest.MonkeyPatch) -> None:
    state = _wire(monkeypatch)

    def boom():
        raise RuntimeError("sina blocked")

    def em_payload():
        return [
            {"board": "main", "pe_median": 12, "pe_equal": 13, "pb_median": 1.2,
             "pb_equal": 1.3, "sample_size": 3000},
            {"board": "chinext", "pe_median": 30, "pe_equal": 31, "pb_median": 3.0,
             "pb_equal": 3.1, "sample_size": 1200},
            {"board": "star", "pe_median": 40, "pe_equal": 41, "pb_median": 4.0,
             "pb_equal": 4.1, "sample_size": 500},
            {"board": "bse", "pe_median": 18, "pe_equal": 19, "pb_median": 2.0,
             "pb_equal": 2.1, "sample_size": 200},
            {"board": "all", "pe_median": 20, "pe_equal": 21, "pb_median": 2.0,
             "pb_equal": 2.1, "sample_size": 4900},
        ]

    summary = mv.compute(_FakeConn(), as_of=TARGET, now=datetime(2026, 11, 27, 21, 20, tzinfo=CN),
                         fetch_sina=boom, fetch_em=em_payload)
    assert summary["status"] == "ok"
    assert summary["source"] == mv.CALC_SRC_EM
    assert state["written"]["calc_src"] == mv.CALC_SRC_EM


def test_compute_graceful_when_all_sources_down(monkeypatch: pytest.MonkeyPatch) -> None:
    state = _wire(monkeypatch)

    def boom():
        raise RuntimeError("blocked")

    summary = mv.compute(_FakeConn(), as_of=TARGET, now=datetime(2026, 11, 27, 21, 20, tzinfo=CN),
                         fetch_sina=boom, fetch_em=boom)
    assert summary["status"] == "unavailable"
    assert summary["error"]
    assert state["written"] == {}, "源全挂时不得写脏数据"
    unavailable = [item for item in state["statuses"] if item["status"] == "unavailable"]
    assert unavailable and "不可用" in unavailable[0]["note"]


def test_compute_rejects_small_sample_and_degrades(monkeypatch: pytest.MonkeyPatch) -> None:
    state = _wire(monkeypatch)
    tiny = [{"symbol": "sh600000", "code": "600000", "per": 10, "pb": 1.0}]

    def boom():
        raise RuntimeError("sina blocked")

    summary = mv.compute(_FakeConn(), as_of=TARGET, now=datetime(2026, 11, 27, 21, 20, tzinfo=CN),
                         fetch_sina=lambda: tiny, fetch_em=boom)
    assert summary["status"] == "unavailable"
    assert state["written"] == {}


def test_resolve_trade_date_returns_none_before_close_not_previous_day() -> None:
    """P1-3：盘中不得回退到前一交易日（否则实时快照会覆盖历史收盘）。"""
    before_conn = _FakeConn([(TARGET,)])
    before = mv.resolve_trade_date(before_conn, now=datetime(2026, 11, 27, 14, 0, tzinfo=CN))
    assert before is None, "收盘确认前必须返回 None，绝不能返回前一交易日"
    assert before_conn.statements[-1][1][0] == TARGET  # 查询参考日仍是今天

    conn_after = _FakeConn([(TARGET,)])
    after = mv.resolve_trade_date(conn_after, now=datetime(2026, 11, 27, 21, 0, tzinfo=CN))
    assert after == TARGET

    # 非交易日（周六）：最近交易日已收盘确认 -> 可写
    weekend = _FakeConn([(TARGET,)])
    assert mv.resolve_trade_date(weekend, now=datetime(2026, 11, 28, 10, 0, tzinfo=CN)) == TARGET


def test_compute_pre_close_skips_without_writing(monkeypatch: pytest.MonkeyPatch) -> None:
    """盘中（15:10 前）compute 必须跳过写库并写 freshness unavailable note。"""
    state = _wire(monkeypatch)
    conn = _FakeConn([(TARGET,)])
    summary = mv.compute(
        conn, now=datetime(2026, 11, 27, 14, 0, tzinfo=CN),
        fetch_sina=lambda: _sina_rows(),
    )
    assert summary["status"] == "skipped"
    assert summary["skip_reason"] == "not_closed"
    assert summary["error"] == "not_closed"
    assert state["written"] == {}, "盘中不得写 bp_market_valuation_daily"
    unavailable = [item for item in state["statuses"] if item["status"] == "unavailable"]
    assert unavailable and "收盘确认" in unavailable[0]["note"]
    assert unavailable[0]["as_of"] is None


def test_compute_rejects_explicit_unconfirmed_as_of(monkeypatch: pytest.MonkeyPatch) -> None:
    """显式 --date=today 但未收盘确认：同样跳过，不得覆盖历史。"""
    state = _wire(monkeypatch)
    summary = mv.compute(
        _FakeConn(), as_of=TARGET,
        now=datetime(2026, 11, 27, 14, 30, tzinfo=CN),
        fetch_sina=lambda: _sina_rows(),
    )
    assert summary["status"] == "skipped"
    assert summary["skip_reason"] == "not_closed"
    assert state["written"] == {}


def test_compute_rejects_future_as_of(monkeypatch: pytest.MonkeyPatch) -> None:
    state = _wire(monkeypatch)
    summary = mv.compute(
        _FakeConn(), as_of=date(2026, 11, 30),
        now=datetime(2026, 11, 27, 21, 0, tzinfo=CN),
        fetch_sina=lambda: _sina_rows(),
    )
    assert summary["status"] == "skipped"
    assert summary["skip_reason"] == "future_date"
    assert state["written"] == {}


def test_compute_rejects_non_trading_as_of(monkeypatch: pytest.MonkeyPatch) -> None:
    """显式 as_of 是交易日历里标记的非交易日：拒绝写入。"""
    state = _wire(monkeypatch)
    conn = _FakeConn([(False,)])  # is_trading = False
    summary = mv.compute(
        conn, as_of=date(2026, 11, 22),  # 周日
        now=datetime(2026, 11, 27, 21, 0, tzinfo=CN),
        fetch_sina=lambda: _sina_rows(),
    )
    assert summary["status"] == "skipped"
    assert summary["skip_reason"] == "not_trading_day"
    assert state["written"] == {}


def test_compute_after_close_confirmation_writes(monkeypatch: pytest.MonkeyPatch) -> None:
    """15:10 之后默认路径正常写当日快照（回归保护）。"""
    state = _wire(monkeypatch)
    conn = _FakeConn([(TARGET,), (TARGET,)])  # candidate + is_trading
    summary = mv.compute(
        conn, now=datetime(2026, 11, 27, 15, 20, tzinfo=CN),
        fetch_sina=lambda: _sina_rows(),
    )
    assert summary["status"] == "ok"
    assert state["written"]["trade_date"] == TARGET
