"""L3 惰性清洗测试：ETL 资产回测首次使用时按需清洗。"""
from __future__ import annotations

from datetime import date

import pytest

from bp_api import repositories


class FakeCursor:
    def __init__(self, conn: "FakeConn") -> None:
        self.conn = conn

    def __enter__(self) -> "FakeCursor":
        return self

    def __exit__(self, *exc: object) -> bool:
        return False

    def execute(self, sql: str, params: object = None) -> None:
        self.conn.queries.append((sql, params))
        self.conn._rows = self.conn.results.pop(0) if self.conn.results else []

    def fetchone(self) -> object:
        return self.conn._rows[0] if self.conn._rows else None

    def fetchall(self) -> list:
        return self.conn._rows


class FakeConn:
    def __init__(self, results: list) -> None:
        self.results = list(results)
        self.queries: list[tuple[str, object]] = []
        self._rows: list = []
        self.commits = 0

    def cursor(self) -> FakeCursor:
        return FakeCursor(self)

    def commit(self) -> None:
        self.commits += 1


def test_ensure_etl_clean_runs_when_clean_missing(monkeypatch: pytest.MonkeyPatch) -> None:
    calls: list[tuple] = []
    monkeypatch.setattr(repositories, "_etl_calendar", lambda: object())
    from bp_api.quant import cleaning

    monkeypatch.setattr(cleaning, "clean_one", lambda conn, symbol, source, cal, adjust: calls.append((symbol, source, adjust)) or 5)
    # 查询顺序：config adjust；raw max；clean max
    conn = FakeConn([[("hfq",)], [(date(2026, 11, 23),)], [(None,)]])
    repositories._ensure_etl_clean(conn, "600036", "etl_a_stock")
    assert calls == [("600036", "etl_a_stock", "hfq")]
    assert conn.commits == 1


def test_ensure_etl_clean_skips_when_current(monkeypatch: pytest.MonkeyPatch) -> None:
    calls: list[tuple] = []
    from bp_api.quant import cleaning

    monkeypatch.setattr(cleaning, "clean_one", lambda *a, **kw: calls.append(a) or 0)
    conn = FakeConn([[("hfq",)], [(date(2026, 11, 23),)], [(date(2026, 11, 23),)]])
    repositories._ensure_etl_clean(conn, "600036", "etl_a_stock")
    assert calls == []


def test_ensure_etl_clean_ignores_legacy_sources() -> None:
    conn = FakeConn([])
    repositories._ensure_etl_clean(conn, "000300", "cn_index_em")
    assert conn.queries == []
