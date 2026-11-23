"""质量门/健康落库测试（T8）。"""
from __future__ import annotations

from datetime import date, datetime

import pytest

from bp_etl.adapters.base import Bar
from bp_etl.health import (
    RunRecord,
    clear_backlog,
    due_backlog,
    finish_run,
    record_issues,
    record_source_health,
    start_run,
    upsert_backlog,
    upsert_dataset_state,
)
from bp_etl.quality import (
    QualityIssue,
    cross_source_issues,
    evaluate,
    ratio_drift_issues,
    sanitize_bars,
)

D1 = date(2026, 11, 20)
D2 = date(2026, 11, 23)


def _bar(symbol: str, d: date, close: float, *, source: str = "sina_kline",
         adjust: str = "hfq", **overrides: object) -> Bar:
    data = dict(
        symbol=symbol, trade_date=d, open=close - 1, high=close + 1,
        low=close - 2, close=close, volume=100, amount=None,
        pct_change=None, source=source, adjust=adjust,
    )
    data.update(overrides)
    return Bar(**data)  # type: ignore[arg-type]


class FakeCursor:
    def __init__(self, conn: "FakeConn") -> None:
        self.conn = conn
        self.rowcount = 0

    def __enter__(self) -> "FakeCursor":
        return self

    def __exit__(self, *exc: object) -> None:
        return None

    def execute(self, sql: str, params: object = None) -> None:
        self.conn.queries.append((sql, params))
        if "RETURNING run_id" in sql:
            return
        if "FROM bp_etl_backlog" in sql:
            self.conn._fetchall = self.conn.backlog_rows

    def executemany(self, sql: str, payload: list) -> None:
        self.conn.executed.append((sql, list(payload)))

    def fetchone(self) -> object:
        if self.conn.run_id is not None and self.conn.queries and "RETURNING" in self.conn.queries[-1][0]:
            return (self.conn.run_id,)
        return None

    def fetchall(self) -> list:
        return self.conn._fetchall


class FakeConn:
    def __init__(self, *, run_id: int | None = 7, backlog_rows: list | None = None) -> None:
        self.run_id = run_id
        self.backlog_rows = backlog_rows or []
        self.queries: list[tuple[str, object]] = []
        self.executed: list[tuple[str, list]] = []
        self._fetchall: list = []

    def cursor(self) -> FakeCursor:
        return FakeCursor(self)


def test_sanitize_bars_filters_invalid() -> None:
    good = _bar("600036", D2, 43.26)
    low_gt_high = _bar("600037", D2, 10.0, low=11.0, high=9.0)
    non_positive = _bar("600038", D2, 0.0)
    future = _bar("600039", date(2026, 12, 31), 10.0)
    negative_vol = _bar("600040", D2, 10.0, volume=-5)
    rows, issues = sanitize_bars("a_stock", [good, low_gt_high, non_positive, future, negative_vol], today=D2)
    assert [bar.symbol for bar in rows] == ["600036"]
    kinds = {issue.kind for issue in issues}
    assert {"future_date", "close_non_positive", "negative_volume"} <= kinds
    assert all(issue.severity == "error" for issue in issues)


def test_evaluate_coverage_gate() -> None:
    bars = [_bar(str(600000 + i), D2, 10.0) for i in range(99)]
    report = evaluate("a_stock", D2, "hfq", bars, 100, coverage_min=0.995)
    assert not report.ok
    assert report.coverage == pytest.approx(0.99)
    assert report.errors and report.errors[0].kind == "coverage"


def test_evaluate_passes_when_complete() -> None:
    bars = [_bar(str(600000 + i), D2, 10.0) for i in range(100)]
    report = evaluate("a_stock", D2, "hfq", bars, 100, coverage_min=0.995, previous_count=100)
    assert report.ok
    assert not report.errors


def test_evaluate_row_delta_and_freshness() -> None:
    bars = [_bar("600036", D1, 10.0)]
    report = evaluate("a_stock", D2, "hfq", bars, 100, coverage_min=0.5, previous_count=10)
    kinds = {issue.kind for issue in report.issues}
    assert "freshness" in kinds
    assert "row_delta" in kinds


def test_cross_source_bfq_tolerance() -> None:
    primary = [_bar("600036", D2, 10.0, adjust="bfq", source="tencent_qt")]
    check = [_bar("600036", D2, 10.005, adjust="bfq", source="sina_kline")]
    assert cross_source_issues("a_stock", "bfq", primary, check) == []
    check_bad = [_bar("600036", D2, 10.5, adjust="bfq", source="sina_kline")]
    assert cross_source_issues("a_stock", "bfq", primary, check_bad)


def test_cross_source_hfq_uses_returns() -> None:
    primary = [_bar("600036", D1, 100.0), _bar("600036", D2, 101.0)]
    check = [_bar("600036", D1, 50.0), _bar("600036", D2, 50.5)]  # 不同基准、收益率相同
    assert cross_source_issues("a_stock", "hfq", primary, check) == []


def test_ratio_drift_flagged() -> None:
    bfq = [_bar("600036", D1, 10.0, adjust="bfq"), _bar("600036", D2, 10.0, adjust="bfq")]
    hfq_ok = [_bar("600036", D1, 20.0), _bar("600036", D2, 20.0)]
    assert ratio_drift_issues("a_stock", "600036", bfq, hfq_ok) == []
    hfq_drift = [_bar("600036", D1, 20.0), _bar("600036", D2, 21.0)]  # 比率变化 5%
    assert ratio_drift_issues("a_stock", "600036", bfq, hfq_drift)


def test_start_and_finish_run() -> None:
    conn = FakeConn(run_id=11)
    record = RunRecord(dataset="a_stock", trade_date=D2, wave=1, status="running")
    run_id = start_run(conn, record)
    assert run_id == 11
    sql, params = conn.queries[0]
    assert "INSERT INTO bp_etl_run" in sql
    assert params[0] == "a_stock" and params[1] == D2
    finish_run(conn, run_id, RunRecord(dataset="a_stock", trade_date=D2, wave=1, status="ok"))
    sql2, params2 = conn.queries[1]
    assert "UPDATE bp_etl_run" in sql2
    assert params2[-1] == 11


def test_record_source_health_and_issues() -> None:
    conn = FakeConn()
    record_source_health(
        conn, stat_date=D2, dataset="a_stock", source="sina_kline", channel="direct",
        snapshot={"attempts": 5, "ok": 4, "failed": 1, "banned_count": 0,
                  "avg_latency_ms": 120.5, "p95_latency_ms": 300.0},
        coverage_today=0.997,
    )
    sql, params = conn.queries[0]
    assert "ON CONFLICT (stat_date, dataset, source, channel)" in sql
    assert params[1] == "a_stock" and params[-1] == 0.997

    issues = [QualityIssue(dataset="a_stock", kind="ohlc", severity="error", symbol="600036")]
    assert record_issues(conn, issues) == 1
    assert "INSERT INTO bp_etl_quality_issue" in conn.executed[0][0]


def test_dataset_state_upsert() -> None:
    conn = FakeConn()
    upsert_dataset_state(conn, "a_stock", D2, 3)
    sql, params = conn.queries[0]
    assert "INSERT INTO bp_etl_dataset_state" in sql
    assert params == ("a_stock", D2, 3)


def test_backlog_upsert_due_clear() -> None:
    conn = FakeConn(backlog_rows=[("600036",), ("600037",)])
    n = upsert_backlog(
        conn, dataset="a_stock", trade_date=D2, symbols=["600036"],
        reason="coverage", next_retry_at=datetime(2026, 11, 23, 23, 30),
    )
    assert n == 1
    assert "ON CONFLICT (dataset, trade_date, scope, symbol)" in conn.executed[0][0]
    due = due_backlog(conn, "a_stock", datetime(2026, 11, 24, 0, 0))
    assert due == ["600036", "600037"]
    cleared = clear_backlog(conn, "a_stock", D2, ["600036"])
    assert cleared == 0  # FakeCursor.rowcount 默认 0；SQL 形状已由 queries 断言
    assert all(param is not None for _, param in conn.queries if "DELETE FROM bp_etl_backlog" in _)
