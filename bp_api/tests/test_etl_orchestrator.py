"""编排器测试（T9）：无限追赶/退避/backlog/幂等/锁/收盘确认。"""
from __future__ import annotations

from datetime import date, datetime, time as dtime, timedelta, timezone

import pytest

import bp_etl.orchestrator as orch_mod
from bp_etl.adapters.base import Bar
from bp_etl.channels import ChannelManager
from bp_etl.config import EtlConfig
from bp_etl.health import RunRecord
from bp_etl.orchestrator import (
    Orchestrator,
    WaveResult,
    retry_interval,
)
from bp_etl.registry import REGISTRY

CN = timezone(timedelta(hours=8))
D1 = date(2026, 11, 20)
D2 = date(2026, 11, 23)


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

    def executemany(self, sql: str, payload: list) -> None:
        self.conn.executed.append((sql, list(payload)))

    def fetchone(self) -> object:
        if not self.conn.fetchone_queue:
            return None
        value = self.conn.fetchone_queue.pop(0)
        # psycopg 行是 tuple；测试队列允许只写标量，这里统一包成单列行
        if value is not None and not isinstance(value, tuple):
            return (value,)
        return value

    def fetchall(self) -> list:
        if self.conn.fetchall_queue:
            return self.conn.fetchall_queue.pop(0)
        return []


class FakeConn:
    def __init__(
        self,
        *,
        fetchone_queue: list | None = None,
        fetchall_queue: list | None = None,
    ) -> None:
        self.fetchone_queue = list(fetchone_queue or [])
        self.fetchall_queue = list(fetchall_queue or [])
        self.queries: list[tuple[str, object]] = []
        self.executed: list[tuple[str, list]] = []
        self.committed = 0

    def cursor(self) -> FakeCursor:
        return FakeCursor(self)

    def __enter__(self) -> "FakeConn":
        return self

    def __exit__(self, *exc: object) -> None:
        return None

    def commit(self) -> None:
        self.committed += 1


class FakeRunner:
    def __init__(self, spec: object, codes: list[str], bars_by_adjust: dict[str, list[Bar]]) -> None:
        self.spec = spec
        self.codes = codes
        self.bars_by_adjust = bars_by_adjust
        self.fetch_calls: list[tuple[str, int]] = []

    def universe(self, conn: object) -> list[str]:
        return list(self.codes)

    def fetch(self, adjust: str, codes: list[str], trade_date: date, channels: object) -> list:
        self.fetch_calls.append((adjust, len(codes)))
        return list(self.bars_by_adjust.get(adjust, []))


def _bar(symbol: str, d: date = D2, close: float = 10.0, adjust: str = "hfq") -> Bar:
    return Bar(symbol=symbol, trade_date=d, open=close - 1, high=close + 1,
               low=close - 2, close=close, volume=100, source="sina_kline", adjust=adjust)


def _config() -> EtlConfig:
    return EtlConfig(
        db=object(),  # type: ignore[arg-type]
        mode="on", workers=2, relay_sg=None, relay_prologue=None,
        log_level="INFO", rebuild_window=(dtime(1, 0), dtime(5, 0)),
    )


class Recorder:
    def __init__(self) -> None:
        self.calls: list[tuple[str, object]] = []

    def __call__(self, name: str):
        def record(*args: object, **kwargs: object) -> object:
            self.calls.append((name, (args, kwargs)))
            if name == "start_run":
                return 42
            if name == "write_bars":
                return len(args[2])  # type: ignore[index]
            return None
        return record


def _patch(monkeypatch: pytest.MonkeyPatch) -> Recorder:
    rec = Recorder()
    for name in (
        "start_run", "finish_run", "record_issues", "record_source_health",
        "upsert_dataset_state", "upsert_backlog", "clear_backlog",
        "write_bars", "write_navs", "refresh_coverage",
    ):
        monkeypatch.setattr(orch_mod, name, rec(name))
    return rec


def _orchestrator(conn: FakeConn, runner: FakeRunner, *, now: datetime, lock: bool = True) -> Orchestrator:
    orch = Orchestrator(
        _config(),
        runners={runner.spec.name: runner},
        conn_factory=lambda: conn,
        channel_manager=ChannelManager(_config()),
        now_fn=lambda: now,
        sleep_fn=lambda seconds: None,
    )
    monkeypatch_attr = lambda obj, name, value: setattr(obj, name, value)  # noqa: E731
    monkeypatch_attr(orch, "_try_lock", lambda c, d: lock)
    monkeypatch_attr(orch, "_unlock", lambda c, d: None)

    def _db_coverage(conn: object, spec: object, trade_date: object, adjust: str, expected: int) -> float:
        if not expected:
            return 0.0
        bars = runner.bars_by_adjust.get(adjust, [])
        return min(1.0, len(bars) / expected)

    def _db_present(conn: object, spec: object, trade_date: object, adjust: str) -> set[str]:
        return {bar.symbol for bar in runner.bars_by_adjust.get(adjust, [])}

    monkeypatch_attr(orch, "_db_coverage", _db_coverage)
    monkeypatch_attr(orch, "_db_present_symbols", _db_present)
    return orch


def test_retry_interval_is_bounded_and_never_stops() -> None:
    assert retry_interval(1) == timedelta(minutes=10)
    assert retry_interval(3) == timedelta(minutes=20)
    assert retry_interval(9) == timedelta(minutes=30)  # 封顶但永不放弃


def test_run_wave_ok_marks_state_and_clears_backlog(monkeypatch: pytest.MonkeyPatch) -> None:
    rec = _patch(monkeypatch)
    codes = [f"{600000 + i}" for i in range(100)]
    runner = FakeRunner(REGISTRY["a_stock"], codes, {"hfq": [_bar(code) for code in codes]})
    conn = FakeConn(fetchone_queue=[None, (42,)])
    now = datetime(2026, 11, 23, 16, 0, tzinfo=CN)
    orch = _orchestrator(conn, runner, now=now)
    result = orch.run_wave("a_stock", "hfq", trade_date=D2, now=now)
    assert result.ok and result.coverage == pytest.approx(1.0)
    names = [name for name, _ in rec.calls]
    assert "upsert_dataset_state" in names
    assert "upsert_backlog" not in names
    assert "clear_backlog" in names
    assert conn.committed == 1


def test_run_wave_incomplete_writes_backlog(monkeypatch: pytest.MonkeyPatch) -> None:
    rec = _patch(monkeypatch)
    codes = [f"{600000 + i}" for i in range(100)]
    bars = [_bar(code) for code in codes[:90]]
    runner = FakeRunner(REGISTRY["a_stock"], codes, {"hfq": bars})
    conn = FakeConn(fetchone_queue=[None, (42,)])
    now = datetime(2026, 11, 23, 16, 0, tzinfo=CN)
    orch = _orchestrator(conn, runner, now=now)
    result = orch.run_wave("a_stock", "hfq", trade_date=D2, now=now)
    assert not result.ok and result.coverage == pytest.approx(0.9)
    assert result.next_retry_in == timedelta(minutes=10)
    backlog_calls = [(a, k) for name, (a, k) in rec.calls if name == "upsert_backlog"]
    assert backlog_calls
    symbols = backlog_calls[0][1]["symbols"]
    assert len(symbols) == 10
    assert "upsert_dataset_state" not in [name for name, _ in rec.calls]


def test_run_wave_before_schedule_skips(monkeypatch: pytest.MonkeyPatch) -> None:
    _patch(monkeypatch)
    runner = FakeRunner(REGISTRY["a_stock"], ["600036"], {"hfq": [_bar("600036")]})
    conn = FakeConn()
    now = datetime(2026, 11, 23, 15, 0, tzinfo=CN)  # hfq 15:20 开始
    orch = _orchestrator(conn, runner, now=now)
    result = orch.run_wave("a_stock", "hfq", trade_date=D2, now=now)
    assert result.skipped and result.skip_reason == "before_schedule"
    assert runner.fetch_calls == []


def test_run_wave_already_done_skips(monkeypatch: pytest.MonkeyPatch) -> None:
    _patch(monkeypatch)
    runner = FakeRunner(REGISTRY["a_stock"], ["600036"], {"hfq": [_bar("600036")]})
    conn = FakeConn(fetchone_queue=[D2])  # last_success == today（lock 已打桩）
    now = datetime(2026, 11, 23, 16, 0, tzinfo=CN)
    orch = _orchestrator(conn, runner, now=now)
    result = orch.run_wave("a_stock", "hfq", trade_date=D2, now=now)
    assert result.skipped and result.skip_reason == "already_done" and result.ok


def test_run_wave_lock_contention_skips(monkeypatch: pytest.MonkeyPatch) -> None:
    _patch(monkeypatch)
    runner = FakeRunner(REGISTRY["a_stock"], ["600036"], {"hfq": [_bar("600036")]})
    conn = FakeConn()
    now = datetime(2026, 11, 23, 16, 0, tzinfo=CN)
    orch = _orchestrator(conn, runner, now=now, lock=False)
    result = orch.run_wave("a_stock", "hfq", trade_date=D2, now=now)
    assert result.skipped and result.skip_reason == "locked"


def test_confirmed_trade_date_rolls_back_before_close(monkeypatch: pytest.MonkeyPatch) -> None:
    _patch(monkeypatch)
    runner = FakeRunner(REGISTRY["a_stock"], [], {})
    conn = FakeConn(fetchone_queue=[D2, D1])  # 当日候选、前一交易日
    now = datetime(2026, 11, 23, 14, 0, tzinfo=CN)  # A 股收盘确认 15:10 前
    orch = Orchestrator(_config(), runners={"a_stock": runner}, conn_factory=lambda: conn,
                        channel_manager=ChannelManager(_config()), now_fn=lambda: now)
    assert orch.confirmed_trade_date(conn, "A", now) == D1
    now2 = datetime(2026, 11, 23, 16, 0, tzinfo=CN)
    conn2 = FakeConn(fetchone_queue=[D2])
    assert orch.confirmed_trade_date(conn2, "A", now2) == D2


def test_run_due_respects_retry_backoff(monkeypatch: pytest.MonkeyPatch) -> None:
    _patch(monkeypatch)
    codes = [f"{600000 + i}" for i in range(100)]
    runner = FakeRunner(REGISTRY["a_stock"], codes, {"hfq": []})  # 永远未达标
    conn = FakeConn(fetchone_queue=[D2])  # confirmed_trade_date 使用
    now = datetime(2026, 11, 23, 16, 0, tzinfo=CN)
    orch = Orchestrator(_config(), runners={"a_stock": runner}, conn_factory=lambda: conn,
                        channel_manager=ChannelManager(_config()), now_fn=lambda: now,
                        sleep_fn=lambda s: None)
    setattr(orch, "_try_lock", lambda c, d: True)
    setattr(orch, "_unlock", lambda c, d: None)
    outcomes = orch.run_due(now=now)
    assert len(outcomes) == 2  # a_stock 的 bfq/hfq 都应触发（均未达标）
    # 下一轮仍在退避窗口内：不得重复轰炸源
    outcomes2 = orch.run_due(now=now + timedelta(minutes=1))
    assert outcomes2 == []

def test_run_backlog_replays_backlog_trade_date(monkeypatch: pytest.MonkeyPatch) -> None:
    """跨日续跑必须以 backlog 自身 trade_date 重放，不能用"当前确认日"。"""
    from datetime import date as _date

    replay_dates = [_date(2026, 11, 23), _date(2026, 11, 20)]
    monkeypatch.setattr(
        orch_mod, "due_backlog_dates",
        lambda conn, dataset, adjust, now, *, limit=10: list(replay_dates),
    )
    code = "600036"
    runner = FakeRunner(REGISTRY["a_stock"], [code], {"hfq": [_bar(code)]})
    conn = FakeConn()
    now = datetime(2026, 11, 24, 16, 0, tzinfo=CN)
    orch = _orchestrator(conn, runner, now=now)
    seen: list = []

    def fake_run_wave(name: str, adjust: str, **kwargs: object) -> object:
        seen.append(kwargs.get("trade_date"))
        return orch_mod.WaveResult(
            dataset=name, adjust=adjust, trade_date=kwargs["trade_date"],  # type: ignore[arg-type]
            wave=2, ok=True,
        )

    monkeypatch.setattr(orch, "run_wave", fake_run_wave)
    # 库内覆盖未达标 → 必须按 backlog 日期重放（若达标会被对账逻辑直接清理）
    monkeypatch.setattr(orch, "_db_coverage", lambda *a, **kw: 0.0)
    outcomes = orch.run_backlog(now=now)
    # a_stock 有 bfq/hfq 两个口径：每个口径都应按 backlog 日期重放
    assert seen == replay_dates * 2
    assert len(outcomes) == len(replay_dates) * 2

def test_run_backlog_clears_stale_entries_without_fetch(monkeypatch: pytest.MonkeyPatch) -> None:
    """库内覆盖已达标的历史 backlog：直接清理，不再发慢请求。"""
    from datetime import date as _date

    backlog_date = _date(2026, 11, 23)
    monkeypatch.setattr(
        orch_mod, "due_backlog_dates",
        lambda conn, dataset, adjust, now, *, limit=10: [backlog_date],
    )
    cleared: list = []
    monkeypatch.setattr(
        orch_mod, "clear_backlog",
        lambda conn, dataset, trade_date, adjust, symbols=None: cleared.append(
            (dataset, trade_date, adjust)
        ) or 1,
    )
    code = "600036"
    runner = FakeRunner(REGISTRY["a_stock"], [code], {"hfq": [_bar(code)]})
    conn = FakeConn()
    now = datetime(2026, 11, 24, 16, 0, tzinfo=CN)
    orch = _orchestrator(conn, runner, now=now)
    monkeypatch.setattr(orch, "_db_coverage", lambda *a, **kw: 1.0)
    called: list = []
    monkeypatch.setattr(orch, "run_wave", lambda *a, **kw: called.append(kw) or orch_mod.WaveResult(
        dataset="a_stock", adjust="hfq", trade_date=backlog_date, ok=True
    ))
    orch.run_backlog(now=now)
    assert called == [], "达标的历史 backlog 不应再发起抓取波次"
    assert cleared, "应清理达标 backlog"