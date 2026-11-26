"""清洗表读取必须按资产主口径过滤（避免 bfq/hfq 同日重复索引导致回测崩溃）。"""
from __future__ import annotations

import pytest

from bp_api import repositories


class FakeCursor:
    def __init__(self, conn):
        self.conn = conn

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def execute(self, sql, params=None):
        self.conn.queries.append((sql, params))
        self.conn._rows = self.conn.results.pop(0) if self.conn.results else []

    def fetchall(self):
        return self.conn._rows

    def fetchone(self):
        return self.conn._rows[0] if self.conn._rows else None

    def executemany(self, sql, payload):
        self.conn.queries.append((sql, payload))


class FakeConn:
    def __init__(self, results):
        self.results = list(results)
        self.queries = []
        self._rows = []

    def cursor(self):
        return FakeCursor(self)


def test_load_series_filters_primary_adjust() -> None:
    import datetime as dt

    conn = FakeConn([[(dt.date(2026, 11, 25), 10.0, "real")]])
    series = repositories._load_series(conn, "000300", "cn_index_em", "hfq")
    sql, params = conn.queries[0]
    assert "adjust = %s" in sql
    assert params == ("000300", "cn_index_em", "hfq")
    assert len(series) == 1


def test_primary_adjusts_maps_pairs() -> None:
    conn = FakeConn([[("000300", "cn_index_em", "hfq"), ("510300", "etf_em", "bfq")]])
    mapping = repositories._primary_adjusts(
        conn, [("000300", "cn_index_em"), ("510300", "etf_em"), ("MISS", "x")]
    )
    assert mapping == {("000300", "cn_index_em"): "hfq", ("510300", "etf_em"): "bfq"}
    sql, _params = conn.queries[0]
    assert "bp_index_config" in sql
