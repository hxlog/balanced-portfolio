"""P1 验收集成测试（T15）：多波追赶、backlog 跨轮续跑、状态推进、幂等。

用假连接/假 runner 模拟"源晚发布 2 小时 → 持续追赶直到追平"，验证无限追赶语义。
"""
from __future__ import annotations

from datetime import date, datetime, time, timedelta, timezone

import pytest

import bp_etl.orchestrator as orch_mod
from bp_etl.adapters.base import Bar
from bp_etl.channels import ChannelManager
from bp_etl.config import EtlConfig
from bp_etl.health import RunRecord
from bp_etl.orchestrator import Orchestrator
from bp_etl.registry import REGISTRY
from scripts.etl_source_timing_report import summarize_runs

CN = timezone(timedelta(hours=8))
D2 = date(2026, 11, 23)


class FakeCursor:
    def __init__(self, conn: "FakeConn") -> None:
        self.conn = conn
        self.rowcount = 0

    def __enter__(self) -> "FakeCursor":
        return self

    def __exit__(self, *exc: object) -> None:
        return False

    def execute(self, sql: str, params: object = None) -> None:
        self.conn.queries.append((sql, params))

    def fetchone(self) -> object:
        if "max(cal_date)" in self.conn.last_sql():
            return (D2,)
        return None

    def fetchall(self) -> list:
        return []


class FakeConn:
    def __init__(self) -> None:
        self.queries: list[tuple[str, object]] = []
        self.commits = 0

    def cursor(self) -> FakeCursor:
        return FakeCursor(self)

    def __enter__(self) -> "FakeConn":
        return self

    def __exit__(self, *exc: object) -> bool:
        return False

    def commit(self) -> None:
        self.commits += 1

    def last_sql(self) -> str:
        return self.queries[-1][0] if self.queries else ""


class FlakyRunner:
    """前 N-1 次只返回部分数据（模拟源晚发布），第 N 次返回全量。"""

    def __init__(self, codes: list[str], fail_times: int) -> None:
        self.spec = REGISTRY["a_stock"]
        self.codes = codes
        self.fail_times = fail_times
        self.calls = 0

    def universe(self, conn: object) -> list[str]:
        return list(self.codes)

    def fetch(self, adjust: str, codes: list[str], trade_date: date, channels: object) -> list:
        self.calls += 1
        limit = 90 if self.calls <= self.fail_times else len(codes)
        self.last_rows = [
            Bar(symbol=code, trade_date=trade_date, open=9.0, high=11.0, low=8.0,
                close=10.0, volume=100, source="sina_kline", adjust=adjust)
            for code in codes[:limit]
        ]
        return self.last_rows


def _config() -> EtlConfig:
    return EtlConfig(db=object(), mode="on", workers=2, relay_sg=None, relay_prologue=None,
                     log_level="INFO", rebuild_window=(time(1, 0), time(5, 0)))


def test_infinite_catch_up_across_rounds(monkeypatch: pytest.MonkeyPatch) -> None:
    """源晚 20 分钟：第 1 轮未达标 → backlog；第 2 轮（>退避 10 分钟）追平并清 backlog。"""
    calls: dict[str, list] = {"state": [], "backlog": [], "clear": []}
    state: dict[tuple[str, str], date] = {}

    def fake_start_run(conn: object, record: RunRecord) -> int:
        return 1

    def fake_upsert_state(
        conn: object, dataset: str, adjust: str, last_success: date | None, run_id: int | None
    ) -> None:
        if last_success is not None:
            state[(dataset, adjust)] = last_success

    monkeypatch.setattr(orch_mod, "start_run", fake_start_run)
    monkeypatch.setattr(orch_mod, "finish_run", lambda *a, **kw: None)
    monkeypatch.setattr(orch_mod, "record_issues", lambda conn, issues: 0)
    monkeypatch.setattr(orch_mod, "record_source_health", lambda *a, **kw: None)
    monkeypatch.setattr(orch_mod, "upsert_dataset_state", fake_upsert_state)
    monkeypatch.setattr(orch_mod, "upsert_backlog", lambda conn, **kw: calls["backlog"].append(kw))
    monkeypatch.setattr(orch_mod, "clear_backlog", lambda conn, *a, **kw: calls["clear"].append(a))
    monkeypatch.setattr(orch_mod, "write_bars", lambda conn, spec, rows: len(rows))
    monkeypatch.setattr(orch_mod, "refresh_coverage", lambda conn, spec, codes: 0)

    codes = [f"{600000 + i}" for i in range(100)]
    runner = FlakyRunner(codes, fail_times=1)
    conn = FakeConn()
    now1 = datetime(2026, 11, 23, 16, 0, tzinfo=CN)
    orch = Orchestrator(_config(), runners={"a_stock": runner}, conn_factory=lambda: conn,
                        channel_manager=ChannelManager(_config()), now_fn=lambda: now1,
                        sleep_fn=lambda s: None)
    monkeypatch.setattr(orch, "_try_lock", lambda c, d: True)
    monkeypatch.setattr(orch, "_unlock", lambda c, d: None)
    monkeypatch.setattr(
        orch, "_db_coverage",
        lambda conn, spec, td, adjust, expected, codes=None: (
            min(1.0, len(getattr(runner, "last_rows", [])) / expected) if expected else 0.0
        ),
    )
    monkeypatch.setattr(
        orch, "_db_present_symbols",
        lambda conn, spec, td, adjust: {bar.symbol for bar in getattr(runner, "last_rows", [])},
    )
    monkeypatch.setattr(orch, "dataset_last_success", lambda c, d, a: state.get((d, a)))
    monkeypatch.setattr(orch, "latest_trading_day", lambda c, d: D2)
    monkeypatch.setattr(orch, "confirmed_trade_date", lambda c, kind, now=None: D2)

    first = orch.run_due(now=now1)
    by_adjust = {item.adjust: item for item in first}
    assert by_adjust["bfq"].ok is False  # 第 1 次抓取源只回 90/100
    assert by_adjust["hfq"].ok is True   # 第 2 次抓取源已恢复全量
    assert any(kw.get("adjust") == "bfq" for kw in calls["backlog"])
    assert state[("a_stock", "hfq")] == D2
    assert ("a_stock", D2, "hfq") in calls["clear"]

    # 下一次轮次在退避窗口内：不再打源
    early = orch.run_due(now=now1 + timedelta(minutes=1))
    assert early == []
    calls_before = runner.calls

    # 退避结束后：仅 bfq 需要重试 → 全量追平、清 backlog、推进 state
    later = orch.run_due(now=now1 + timedelta(minutes=11))
    assert runner.calls == calls_before + 1
    assert later and later[0].ok and later[0].adjust == "bfq"
    assert ("a_stock", D2, "bfq") in calls["clear"]
    assert state[("a_stock", "bfq")] == D2


def test_timing_report_summary() -> None:
    rows = [
        {"dataset": "a_stock", "adjust": "hfq", "trade_date": D2,
         "first_ok_at": datetime(2026, 11, 23, 16, 40, tzinfo=CN)},
        {"dataset": "a_stock", "adjust": "hfq", "trade_date": D2,
         "first_ok_at": datetime(2026, 11, 23, 16, 20, tzinfo=CN)},
    ]
    targets = {("a_stock", "hfq"): time(16, 30)}
    summary = summarize_runs(rows, targets)
    assert summary["a_stock/hfq"]["samples"] == 2
    assert summary["a_stock/hfq"]["p50_delay_min"] in (10.0, -10.0)
    assert summary["a_stock/hfq"]["target"] == "16:30"

def test_shadow_mode_does_not_write_or_advance_state(monkeypatch: pytest.MonkeyPatch) -> None:
    """shadow：拉取/校验/记录 run，但不写行情表、不刷 coverage、不推进 state、不写 backlog。"""
    effects: dict[str, int] = {"write": 0, "coverage": 0, "state": 0, "backlog": 0, "clear": 0, "run": 0}
    monkeypatch.setattr(orch_mod, "start_run", lambda *a, **kw: effects.__setitem__("run", effects["run"] + 1) or 1)
    monkeypatch.setattr(orch_mod, "finish_run", lambda *a, **kw: None)
    monkeypatch.setattr(orch_mod, "record_issues", lambda *a, **kw: 0)
    monkeypatch.setattr(orch_mod, "record_source_health", lambda *a, **kw: None)
    monkeypatch.setattr(orch_mod, "upsert_dataset_state", lambda *a, **kw: effects.__setitem__("state", effects["state"] + 1))
    monkeypatch.setattr(orch_mod, "upsert_backlog", lambda *a, **kw: effects.__setitem__("backlog", effects["backlog"] + 1))
    monkeypatch.setattr(orch_mod, "clear_backlog", lambda *a, **kw: effects.__setitem__("clear", effects["clear"] + 1))
    monkeypatch.setattr(orch_mod, "write_bars", lambda *a, **kw: effects.__setitem__("write", effects["write"] + 1) or 0)
    monkeypatch.setattr(orch_mod, "refresh_coverage", lambda *a, **kw: effects.__setitem__("coverage", effects["coverage"] + 1))
    runner = FlakyRunner([f"{600000 + i}" for i in range(100)], fail_times=0)
    conn = FakeConn()
    now = datetime(2026, 11, 23, 16, 0, tzinfo=CN)
    orch = Orchestrator(_config(), runners={"a_stock": runner}, conn_factory=lambda: conn,
                        channel_manager=ChannelManager(_config()), now_fn=lambda: now,
                        sleep_fn=lambda s: None, write_enabled=False)
    monkeypatch.setattr(orch, "_try_lock", lambda c, d: True)
    monkeypatch.setattr(orch, "_unlock", lambda c, d: None)
    monkeypatch.setattr(orch, "dataset_last_success", lambda c, d, a: None)
    result = orch.run_wave("a_stock", "hfq", trade_date=D2, now=now)
    assert result.ok
    assert effects["run"] == 1
    assert effects["write"] == effects["coverage"] == effects["state"] == 0
    assert effects["backlog"] == effects["clear"] == 0