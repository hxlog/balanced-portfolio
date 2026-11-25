"""旧行情链 legacy_index runner 测试（P2，离线 fixture）。"""
from __future__ import annotations

import os
from datetime import date
from types import SimpleNamespace

import pytest

from bp_etl.adapters.base import Bar
from bp_etl.datasets.legacy_index import (
    LegacyIndexRunner,
    filter_configs,
    parse_configs,
)
from bp_etl.registry import REGISTRY

D2 = date(2026, 11, 23)


class FakeCursor:
    def __init__(self, conn: "FakeConn") -> None:
        self.conn = conn
        self.rowcount = 0

    def __enter__(self) -> "FakeCursor":
        return self

    def __exit__(self, *exc: object) -> bool:
        return False

    def execute(self, sql: str, params: object = None) -> None:
        self.conn.queries.append((sql, params))

    def fetchall(self) -> list:
        if not self.conn.results:
            return []
        return self.conn.results.pop(0)


class FakeConn:
    def __init__(self, results: list | None = None) -> None:
        self.results = list(results or [])
        self.queries: list[tuple[str, object]] = []
        self.closed = 0

    def cursor(self) -> FakeCursor:
        return FakeCursor(self)

    def close(self) -> None:
        self.closed += 1


class FakeIngest:
    """按 symbol 返回 ok/error；记录每次调用与当时的 BP_HTTP_PROXY。"""

    def __init__(self, *, fail_symbols: set[str] | None = None) -> None:
        self.fail_symbols = fail_symbols or set()
        self.calls: list[dict] = []
        self.proxy_seen: list[str | None] = []

    def run(self, app: object, symbols: list[str], refresh_clean: bool = True) -> list:
        self.calls.append({"symbols": list(symbols), "refresh_clean": refresh_clean})
        self.proxy_seen.append(os.environ.get("BP_HTTP_PROXY"))
        return [
            SimpleNamespace(symbol=symbol, status=("error" if symbol in self.fail_symbols else "ok"))
            for symbol in symbols
        ]


CONFIG_ROWS = [
    ("000300", "cn_index_em", ["bfq"], "bfq"),
    ("510300", "etf_em", ["bfq", "hfq"], "hfq"),
    ("HSI", "hk_index_em", ["bfq"], "bfq"),
]
READBACK_ROWS = [
    ("000300", "cn_index_em", D2, 4000.0, 4010.0, 3990.0, 4005.0, 100, 1000.0, 0.1),
    ("510300", "etf_em", D2, 4.0, 4.1, 3.9, 4.05, 200, 810.0, 0.5),
]


def test_parse_and_filter_configs() -> None:
    configs = parse_configs(CONFIG_ROWS)
    assert len(configs) == 3
    bfq = filter_configs(configs, "bfq")
    hfq = filter_configs(configs, "hfq")
    assert {cfg["symbol"] for cfg in bfq} == {"000300", "510300", "HSI"}
    assert [cfg["symbol"] for cfg in hfq] == ["510300"]
    # adjust_modes 为空时回退 primary adjust
    assert parse_configs([("X", "s", None, "hfq")])[0]["adjust_modes"] == ("hfq",)


def test_universe_sql() -> None:
    conn = FakeConn([[("000300",), ("HSI",)]])
    runner = LegacyIndexRunner(conn_factory=lambda: conn)
    assert runner.universe(conn) == ["000300", "HSI"]
    assert "bp_index_config" in conn.queries[0][0]


def test_fetch_bfq_uses_ingest_and_reads_back() -> None:
    conn = FakeConn([CONFIG_ROWS, READBACK_ROWS])
    ingest = FakeIngest()
    runner = LegacyIndexRunner(conn_factory=lambda: conn, ingest=ingest, app_config=object())
    bars = runner.fetch("bfq", ["000300", "510300", "HSI"], D2, channels=None)  # type: ignore[arg-type]
    assert len(bars) == 2
    assert {bar.symbol for bar in bars} == {"000300", "510300"}
    assert bars[0].source == "cn_index_em"
    assert ingest.calls and ingest.calls[0]["refresh_clean"] is False
    assert conn.closed == 1
    assert any("bp_index_quote_daily" in sql for sql, _ in conn.queries)


def test_fetch_hfq_filters_multi_adjust_configs() -> None:
    conn = FakeConn([CONFIG_ROWS, READBACK_ROWS])
    ingest = FakeIngest()
    runner = LegacyIndexRunner(conn_factory=lambda: conn, ingest=ingest, app_config=object())
    runner.fetch("hfq", ["000300", "510300", "HSI"], D2, channels=None)  # type: ignore[arg-type]
    assert ingest.calls[0]["symbols"] == ["510300"]


def test_fetch_chunks_and_relay_second_pass(monkeypatch: pytest.MonkeyPatch) -> None:
    conn = FakeConn([CONFIG_ROWS, []])
    ingest = FakeIngest(fail_symbols={"000300"})
    runner = LegacyIndexRunner(
        conn_factory=lambda: conn, ingest=ingest, app_config=object(),
        relay_proxy="http://127.0.0.1:10809", chunk_size=2,
    )
    monkeypatch.delenv("BP_HTTP_PROXY", raising=False)
    runner.fetch("bfq", ["000300", "510300", "HSI"], D2, channels=None)  # type: ignore[arg-type]
    assert [call["symbols"] for call in ingest.calls] == [
        ["000300", "510300"],
        ["HSI"],
        ["000300"],  # relay 二次只重试失败标的
    ]
    assert ingest.proxy_seen[0] is None
    assert ingest.proxy_seen[-1] == "http://127.0.0.1:10809"
    assert "BP_HTTP_PROXY" not in os.environ  # 用后恢复


def test_runner_registered_in_registry() -> None:
    spec = REGISTRY["legacy_index"]
    assert spec.table == "bp_index_quote_daily"
    assert spec.anchor["bfq"] == "legacy_multi"
def test_universe_scope_selectable(monkeypatch) -> None:
    """生产默认只跑可选资产 + 汇率源（避免不可达自定义指数拖慢每夜迁移）。"""
    from bp_etl.datasets.legacy_index import LegacyIndexRunner

    class FakeCursor:
        def __enter__(self): return self
        def __exit__(self, *exc): return False
        def execute(self, sql, params=None): self.sql = sql
        def fetchall(self): return [("000300",)]

    class FakeConn:
        def cursor(self): return FakeCursor()

    monkeypatch.setenv("BP_ETL_LEGACY_SCOPE", "selectable")
    monkeypatch.delenv("BP_ETL_LEGACY_SYMBOLS", raising=False)
    runner = LegacyIndexRunner()
    conn = FakeConn()
    symbols = runner.universe(conn)
    assert symbols == ["000300"]
