"""旧链清洗钩子：legacy 波次成功后触发刷新，失败不阻断。"""
from __future__ import annotations

import datetime as dt
from datetime import date
from zoneinfo import ZoneInfo

import pytest

import bp_etl.orchestrator as orch_mod
from bp_etl.adapters.base import Bar
from bp_etl.channels import ChannelManager
from bp_etl.config import EtlConfig
from bp_etl.orchestrator import Orchestrator
from bp_etl.registry import REGISTRY

CN = ZoneInfo("Asia/Shanghai")
D2 = date(2026, 11, 24)


class FakeConn:
    def __init__(self) -> None:
        self.queries: list = []
        self.committed = 0
        self._rows: list = []

    def cursor(self) -> "FakeConn":
        return self

    def __enter__(self) -> "FakeConn":
        return self

    def __exit__(self, *exc: object) -> bool:
        return False

    def execute(self, sql: str, params: object = None) -> None:
        self.queries.append((sql, params))
        self._rows = []

    def fetchone(self) -> object:
        return None

    def fetchall(self) -> list:
        return []

    def commit(self) -> None:
        self.committed += 1

    def rollback(self) -> None:
        pass

    def close(self) -> None:
        pass


class FakeRunner:
    spec = REGISTRY["legacy_index"]

    def __init__(self, codes: list[str], bars: dict) -> None:
        self.codes = codes
        self.bars = bars
        self.calls: list = []

    def universe(self, conn: object) -> list[str]:
        return list(self.codes)

    def fetch(self, adjust: str, codes: list[str], trade_date: date, channels: object) -> list:
        self.calls.append((adjust, len(codes)))
        return list(self.bars.get(adjust, []))


def _config() -> EtlConfig:
    return EtlConfig(
        db=object(), mode="on", workers=2, relay_sg=None, relay_prologue=None,
        log_level="INFO", rebuild_window=(dt.time(1, 0), dt.time(5, 0)),
    )


def test_legacy_wave_triggers_clean_hook(monkeypatch: pytest.MonkeyPatch) -> None:
    calls: list[object] = []
    monkeypatch.setattr(
        "bp_etl.cleaning_hook.refresh_legacy_clean", lambda conn: calls.append(conn) or {}
    )
    for name in (
        "start_run", "finish_run", "record_issues", "record_source_health",
        "upsert_dataset_state", "upsert_backlog", "clear_backlog",
        "write_bars", "write_navs", "refresh_coverage",
    ):
        monkeypatch.setattr(orch_mod, name, lambda *a, **kw: 1)
    runner = FakeRunner(
        ["000300"],
        {"hfq": [Bar(symbol="000300", trade_date=D2, open=1, high=2, low=0.5, close=1.5,
                     volume=10, source="cn_index_em", adjust="hfq")]},
    )
    conn = FakeConn()
    now = dt.datetime(2026, 11, 24, 16, 30, tzinfo=CN)
    orch = Orchestrator(
        _config(),
        runners={"legacy_index": runner},
        conn_factory=lambda: conn,
        channel_manager=ChannelManager(_config()),
        now_fn=lambda: now,
        sleep_fn=lambda seconds: None,
    )
    monkeypatch.setattr(orch, "_try_lock", lambda c, d: True)
    monkeypatch.setattr(orch, "_unlock", lambda c, d: None)
    monkeypatch.setattr(orch, "_db_coverage", lambda *a, **kw: 1.0)
    monkeypatch.setattr(orch, "_db_present_symbols", lambda *a, **kw: {"000300"})
    result = orch.run_wave("legacy_index", "hfq", trade_date=D2, now=now)
    assert result.ok
    assert calls, "legacy hfq 波次成功后应触发清洗刷新钩子"


def test_legacy_hook_failure_does_not_break_wave(monkeypatch: pytest.MonkeyPatch) -> None:
    def boom(conn: object) -> dict:
        raise RuntimeError("cleaning boom")

    monkeypatch.setattr("bp_etl.cleaning_hook.refresh_legacy_clean", boom)
    for name in (
        "start_run", "finish_run", "record_issues", "record_source_health",
        "upsert_dataset_state", "upsert_backlog", "clear_backlog",
        "write_bars", "write_navs", "refresh_coverage",
    ):
        monkeypatch.setattr(orch_mod, name, lambda *a, **kw: 1)
    runner = FakeRunner(
        ["000300"],
        {"bfq": [Bar(symbol="000300", trade_date=D2, open=1, high=2, low=0.5, close=1.5,
                     volume=10, source="cn_index_em", adjust="bfq")]},
    )
    conn = FakeConn()
    now = dt.datetime(2026, 11, 24, 16, 30, tzinfo=CN)
    orch = Orchestrator(
        _config(),
        runners={"legacy_index": runner},
        conn_factory=lambda: conn,
        channel_manager=ChannelManager(_config()),
        now_fn=lambda: now,
        sleep_fn=lambda seconds: None,
    )
    monkeypatch.setattr(orch, "_try_lock", lambda c, d: True)
    monkeypatch.setattr(orch, "_unlock", lambda c, d: None)
    monkeypatch.setattr(orch, "_db_coverage", lambda *a, **kw: 1.0)
    monkeypatch.setattr(orch, "_db_present_symbols", lambda *a, **kw: {"000300"})
    result = orch.run_wave("legacy_index", "hfq", trade_date=D2, now=now)
    assert result.ok, "清洗钩子异常不应影响 legacy 波次结果"

def test_legacy_clean_triggered_even_when_coverage_short(monkeypatch: pytest.MonkeyPatch) -> None:
    """覆盖率未达标（旧链有不可达指数）时，只要本轮有抓取也应刷新清洗。"""
    calls: list[object] = []
    monkeypatch.setattr(
        "bp_etl.cleaning_hook.refresh_legacy_clean", lambda conn: calls.append(conn) or {}
    )
    for name in (
        "start_run", "finish_run", "record_issues", "record_source_health",
        "upsert_dataset_state", "upsert_backlog", "clear_backlog",
        "write_bars", "write_navs", "refresh_coverage",
    ):
        monkeypatch.setattr(orch_mod, name, lambda *a, **kw: 1)
    runner = FakeRunner(
        ["000300"],
        {"hfq": [Bar(symbol="000300", trade_date=D2, open=1, high=2, low=0.5, close=1.5,
                     volume=10, source="cn_index_em", adjust="hfq")]},
    )
    conn = FakeConn()
    now = dt.datetime(2026, 11, 24, 17, 0, tzinfo=CN)
    orch = Orchestrator(
        _config(),
        runners={"legacy_index": runner},
        conn_factory=lambda: conn,
        channel_manager=ChannelManager(_config()),
        now_fn=lambda: now,
        sleep_fn=lambda seconds: None,
    )
    monkeypatch.setattr(orch, "_try_lock", lambda c, d: True)
    monkeypatch.setattr(orch, "_unlock", lambda c, d: None)
    monkeypatch.setattr(orch, "_db_coverage", lambda *a, **kw: 0.5)  # 未达标
    monkeypatch.setattr(orch, "_db_present_symbols", lambda *a, **kw: {"000300"})
    result = orch.run_wave("legacy_index", "hfq", trade_date=D2, now=now)
    assert result.ok is False
    assert calls, "未达标但有抓取时也应刷新旧链清洗"
