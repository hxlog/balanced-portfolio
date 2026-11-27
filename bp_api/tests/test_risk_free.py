"""10Y 国债免费源（chinabond/akshare/sina）与优雅降级测试（纯 mock）。"""
from __future__ import annotations

from datetime import date, datetime, timezone, timedelta
from types import SimpleNamespace

import pytest

from bp_ingest import risk_free

CN = timezone(timedelta(hours=8))
TODAY = date(2026, 11, 27)


def test_normalize_rows_validates_date_and_value_range() -> None:
    rows = risk_free.normalize_rows(
        [
            {"trade_date": "2026-11-26", "value": 1.85},
            {"trade_date": "2026-11-27", "value": "1.83"},
            {"trade_date": "2026-11-27", "value": 1.84},  # 同日去重保留最后
            {"trade_date": "2026-11-28", "value": 99.0},  # 越界丢弃
            {"trade_date": "bad", "value": 1.8},
            {"trade_date": "2026-11-25", "value": 0.0},  # 0 无效
        ],
        source="chinabond",
    )
    assert [row["trade_date"] for row in rows] == [date(2026, 11, 26), date(2026, 11, 27)]
    assert rows[-1]["value"] == pytest.approx(1.84)
    assert all(row["source"] == "chinabond" for row in rows)


def _rows(days: int = 3) -> list[dict]:
    return [
        {"trade_date": date(2026, 11, 25) + timedelta(days=index), "value": 1.8 + 0.01 * index,
         "source": "akshare"}
        for index in range(days)
    ]


def test_run_falls_back_to_akshare_when_chinabond_fails(monkeypatch: pytest.MonkeyPatch) -> None:
    written: list = []
    statuses: list = []

    def chinabond(start, end):
        raise risk_free.RiskFreeUnavailable("chinabond 维护")

    monkeypatch.setattr(risk_free, "last_stored_date", lambda conn: None)
    monkeypatch.setattr(risk_free, "upsert_rows", lambda conn, rows: written.extend(rows) or len(rows))
    monkeypatch.setattr(
        risk_free, "_record_status",
        lambda conn, as_of, status, note, **kw: statuses.append(
            {"as_of": as_of, "status": status, "note": note, **kw}
        ),
    )
    fetchers = {
        "chinabond": chinabond,
        "akshare": lambda start, end: _rows(3),
    }
    summary = risk_free.run(
        SimpleNamespace(), start=date(2026, 11, 24), end=TODAY, fetchers=fetchers,
        now=datetime(2026, 11, 27, 21, 0, tzinfo=CN),
    )
    assert summary["status"] == "ok"
    assert summary["source"] == "akshare"
    assert summary["rows_written"] == 3
    assert written and written[-1]["trade_date"] == date(2026, 11, 27)
    assert statuses and statuses[-1]["status"] == "ok"


def test_run_records_unavailable_without_writing(monkeypatch: pytest.MonkeyPatch) -> None:
    upserts: list = []
    statuses: list = []

    def boom(start, end):
        raise RuntimeError("blocked")

    monkeypatch.setattr(risk_free, "last_stored_date", lambda conn: None)
    monkeypatch.setattr(risk_free, "upsert_rows", lambda conn, rows: upserts.append(rows) or len(rows))
    monkeypatch.setattr(
        risk_free, "_record_status",
        lambda conn, as_of, status, note, **kw: statuses.append((status, note)),
    )
    fetchers = {"chinabond": boom, "akshare": boom, "sina": boom}
    summary = risk_free.run(SimpleNamespace(), start=date(2026, 11, 1), end=TODAY,
                            fetchers=fetchers, now=datetime(2026, 11, 27, 21, 0, tzinfo=CN))
    assert summary["status"] == "unavailable"
    assert upserts == []
    assert statuses and statuses[-1][0] == "unavailable"
    assert "不可用" in statuses[-1][1]


def test_run_dry_run_does_not_write(monkeypatch: pytest.MonkeyPatch) -> None:
    upserts: list = []
    monkeypatch.setattr(risk_free, "last_stored_date", lambda conn: None)
    monkeypatch.setattr(risk_free, "upsert_rows", lambda conn, rows: upserts.append(rows) or len(rows))
    monkeypatch.setattr(risk_free, "_record_status", lambda *a, **kw: None)
    summary = risk_free.run(
        SimpleNamespace(), start=date(2026, 11, 20), end=TODAY, dry_run=True,
        fetchers={"chinabond": lambda start, end: _rows(2)},
        now=datetime(2026, 11, 27, 21, 0, tzinfo=CN),
    )
    assert summary["status"] == "ok" and summary["dry_run"] is True
    assert upserts == []


def test_upsert_sql_conflict_target_is_series_date() -> None:
    """写入口径必须 upsert 到 (series_code, trade_date)，source 记录实际来源。"""
    conn_queries: list = []

    class Cur:
        def executemany(self, sql, payload):
            conn_queries.append((sql, payload))

        def __enter__(self):
            return self

        def __exit__(self, *exc):
            return False

    class Conn:
        def cursor(self):
            return Cur()

        def commit(self):
            pass

    written = risk_free.upsert_rows(Conn(), _rows(2))
    assert written == 2
    sql, payload = conn_queries[0]
    assert "ON CONFLICT (series_code, trade_date)" in sql
    assert payload[0][0] == "cn_10y_yield"
    assert payload[0][3] == "%"
