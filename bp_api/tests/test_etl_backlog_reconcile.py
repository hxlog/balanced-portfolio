"""backlog 对账：当前 universe 收敛、超期放弃；repair_quote_clean 计划/SQL（纯 mock）。"""
from __future__ import annotations

import importlib.util
import sys
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

import pytest

import bp_etl.orchestrator as orch_mod
from bp_etl.adapters.base import Bar
from bp_etl.channels import ChannelManager
from bp_etl.config import EtlConfig
from bp_etl.health import (
    prune_backlog_symbols,
    purge_backlog_before,
    purge_backlog_dates,
)
from bp_etl.orchestrator import Orchestrator
from bp_etl.registry import REGISTRY

ROOT = Path(__file__).resolve().parents[2]
_SPEC = importlib.util.spec_from_file_location(
    "repair_quote_clean", ROOT / "scripts" / "repair_quote_clean.py"
)
rqc = importlib.util.module_from_spec(_SPEC)
sys.modules["repair_quote_clean"] = rqc
_SPEC.loader.exec_module(rqc)  # type: ignore[union-attr]

CN = timezone(timedelta(hours=8))
D2 = date(2026, 11, 26)


# ---------------------------------------------------------------------------
# health：SQL 与参数
# ---------------------------------------------------------------------------
class FakeCursor:
    def __init__(self, conn: "FakeConn") -> None:
        self.conn = conn
        self.rowcount = conn.rowcount

    def execute(self, sql: str, params: object = None) -> None:
        self.conn.queries.append((sql, params))

    def executemany(self, sql: str, payload: list) -> None:
        self.conn.executed.append((sql, list(payload)))

    def fetchone(self):
        return self.conn.fetchone_queue.pop(0) if self.conn.fetchone_queue else None

    def fetchall(self):
        return self.conn.fetchall_queue.pop(0) if self.conn.fetchall_queue else []

    def __enter__(self):
        return self

    def __exit__(self, *exc: object) -> bool:
        return False


class FakeConn:
    def __init__(self, *, rowcount: int = 0, fetchone=None, fetchall=None) -> None:
        self.queries: list = []
        self.executed: list = []
        self.committed = 0
        self.rowcount = rowcount
        self.fetchone_queue = list(fetchone or [])
        self.fetchall_queue = list(fetchall or [])

    def cursor(self):
        return FakeCursor(self)

    def commit(self) -> None:
        self.committed += 1

    def rollback(self) -> None:
        pass

    def __enter__(self):
        return self

    def __exit__(self, *exc: object) -> bool:
        return False


def test_prune_backlog_symbols_deletes_non_universe_only() -> None:
    conn = FakeConn(rowcount=9434)
    removed = prune_backlog_symbols(conn, "legacy_index", "bfq", ["000300", "000905"])
    assert removed == 9434
    sql, params = conn.queries[0]
    assert "DELETE FROM bp_etl_backlog" in sql
    assert "NOT (symbol = ANY(%s))" in sql
    assert params[0] == "legacy_index" and params[1] == "bfq"
    assert params[2] == ["000300", "000905"]


def test_prune_backlog_symbols_empty_universe_is_noop() -> None:
    conn = FakeConn(rowcount=99)
    assert prune_backlog_symbols(conn, "legacy_index", "bfq", []) == 0
    assert conn.queries == [], "universe 为空时不得删除 backlog"


def test_purge_helpers_sql() -> None:
    conn = FakeConn(rowcount=5)
    assert purge_backlog_dates(conn, "legacy_index", "hfq", [date(2026, 11, 25)]) == 5
    sql, params = conn.queries[0]
    assert "trade_date = ANY(%s)" in sql and params == ("legacy_index", "hfq", [date(2026, 11, 25)])

    conn2 = FakeConn(rowcount=7)
    assert purge_backlog_before(conn2, "legacy_index", "hfq", date(2026, 11, 1)) == 7
    assert "trade_date < %s" in conn2.queries[0][0]


# ---------------------------------------------------------------------------
# orchestrator.run_backlog：当前 universe + trade_date 对账
# ---------------------------------------------------------------------------
def _config() -> EtlConfig:
    return EtlConfig(
        db=object(), mode="on", workers=2, relay_sg=None, relay_prologue=None,
        log_level="INFO", rebuild_window=(datetime.min.time(), datetime.min.time()),
    )


class FakeRunner:
    spec = REGISTRY["a_stock"]

    def __init__(self, codes: list[str]) -> None:
        self.codes = codes
        self.fetch_calls: list = []

    def universe(self, conn: object) -> list[str]:
        return list(self.codes)

    def fetch(self, adjust: str, codes: list[str], trade_date: date, channels: object) -> list:
        self.fetch_calls.append((adjust, len(codes)))
        return [Bar(symbol=code, trade_date=D2, open=1, high=2, low=0.5, close=1.5,
                    volume=1, source="tencent_qt", adjust=adjust) for code in codes]


def _orchestrator(monkeypatch: pytest.MonkeyPatch, conn: FakeConn, runner: FakeRunner, *, now: datetime):
    orch = Orchestrator(
        _config(), runners={runner.spec.name: runner}, conn_factory=lambda: conn,
        channel_manager=ChannelManager(_config()), now_fn=lambda: now,
        sleep_fn=lambda seconds: None,
    )
    monkeypatch.setattr(orch, "_try_lock", lambda c, d: True)
    monkeypatch.setattr(orch, "_unlock", lambda c, d: None)
    monkeypatch.setattr(orch_mod, "start_run", lambda *a, **kw: 1)
    for name in ("finish_run", "record_issues", "record_source_health", "upsert_dataset_state",
                 "upsert_backlog"):
        monkeypatch.setattr(orch_mod, name, lambda *a, **kw: 1)
    return orch


def test_run_backlog_prunes_stale_universe_symbols(monkeypatch: pytest.MonkeyPatch) -> None:
    conn = FakeConn()
    runner = FakeRunner(["000300", "000905"])
    now = datetime(2026, 11, 27, 16, 0, tzinfo=CN)
    orch = _orchestrator(monkeypatch, conn, runner, now=now)

    pruned: list = []
    monkeypatch.setattr(
        orch_mod, "prune_backlog_symbols",
        lambda c, dataset, adjust, codes: pruned.append((dataset, adjust, tuple(codes))) or 9000,
    )
    monkeypatch.setattr(orch_mod, "due_backlog_dates", lambda c, n, a, now, limit=10: [])
    orch.run_backlog(now=now)
    assert pruned, "应调用旧 universe symbol 收敛"
    assert pruned[0][2] == ("000300", "000905")


def test_run_backlog_reconciles_by_current_universe_coverage(monkeypatch: pytest.MonkeyPatch) -> None:
    conn = FakeConn()
    runner = FakeRunner(["000300", "000905"])
    now = datetime(2026, 11, 27, 16, 0, tzinfo=CN)
    orch = _orchestrator(monkeypatch, conn, runner, now=now)
    monkeypatch.setattr(orch_mod, "prune_backlog_symbols", lambda *a, **kw: 0)
    monkeypatch.setattr(orch_mod, "due_backlog_dates", lambda c, n, a, now, limit=10: [D2])
    cleared: list = []
    monkeypatch.setattr(
        orch_mod, "clear_backlog",
        lambda c, dataset, trade_date, adjust, symbols=None: cleared.append((dataset, trade_date, adjust)) or 1,
    )
    seen_codes: dict = {}

    def fake_coverage(conn_, spec, trade_date, adjust, expected, codes=None):
        seen_codes["codes"] = codes
        return 1.0  # 当前 universe 已补齐

    monkeypatch.setattr(orch, "_db_coverage", fake_coverage)
    called: list = []
    monkeypatch.setattr(orch, "run_wave", lambda *a, **kw: called.append(kw))
    orch.run_backlog(now=now)
    assert seen_codes["codes"] == ["000300", "000905"], "覆盖率必须按当前 universe 计算"
    assert cleared and called == [], "已达标应清 backlog 且不再抓取"


def test_run_backlog_default_never_drops_expired_history_dates(monkeypatch: pytest.MonkeyPatch) -> None:
    """P1-1：默认（未显式设置 BP_ETL_BACKLOG_MAX_AGE_DAYS）永不丢弃历史缺口。"""
    monkeypatch.delenv("BP_ETL_BACKLOG_MAX_AGE_DAYS", raising=False)
    conn = FakeConn()
    runner = FakeRunner(["000300"])
    now = datetime(2026, 11, 27, 16, 0, tzinfo=CN)
    orch = _orchestrator(monkeypatch, conn, runner, now=now)
    monkeypatch.setattr(orch_mod, "prune_backlog_symbols", lambda *a, **kw: 0)
    old_date = date(2026, 11, 10)  # 17 天前：长假/源故障造成的真实缺口
    monkeypatch.setattr(orch_mod, "due_backlog_dates", lambda c, n, a, now, limit=10: [old_date])
    monkeypatch.setattr(orch, "_db_coverage", lambda *a, **kw: 0.0)
    dropped: list = []
    monkeypatch.setattr(
        orch_mod, "clear_backlog",
        lambda c, dataset, trade_date, adjust, symbols=None: dropped.append(trade_date) or 9,
    )
    called: list = []
    monkeypatch.setattr(orch, "run_wave", lambda *a, **kw: called.append(kw))
    orch.run_backlog(now=now)
    assert dropped == [], "默认关闭时不得丢弃任何历史日期（否则留下永久空洞）"
    assert [kw["trade_date"] for kw in called] == [old_date, old_date], \
        "超期历史缺口应继续按 backlog 日期跨日重放（bfq/hfq 各一次）"


def test_run_backlog_explicit_max_age_drops_with_quality_alert(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """显式开启超期丢弃时：清理 backlog 且必须写 bp_etl_quality_issue 告警。"""
    monkeypatch.setenv("BP_ETL_BACKLOG_MAX_AGE_DAYS", "5")
    conn = FakeConn()
    runner = FakeRunner(["000300"])
    now = datetime(2026, 11, 27, 16, 0, tzinfo=CN)
    orch = _orchestrator(monkeypatch, conn, runner, now=now)
    assert orch._backlog_max_age_days == 5
    monkeypatch.setattr(orch_mod, "prune_backlog_symbols", lambda *a, **kw: 0)
    old_date = date(2026, 11, 10)  # age=17 > 5
    monkeypatch.setattr(orch_mod, "due_backlog_dates", lambda c, n, a, now, limit=10: [old_date])
    monkeypatch.setattr(orch, "_db_coverage", lambda *a, **kw: 0.0)
    dropped: list = []
    monkeypatch.setattr(
        orch_mod, "clear_backlog",
        lambda c, dataset, trade_date, adjust, symbols=None: dropped.append(trade_date) or 9,
    )
    issues: list = []
    monkeypatch.setattr(
        orch_mod, "record_issues", lambda c, items: issues.extend(items) or len(items)
    )
    called: list = []
    monkeypatch.setattr(orch, "run_wave", lambda *a, **kw: called.append(kw))
    orch.run_backlog(now=now)
    assert dropped == [old_date, old_date], "显式开启后超期日期应放弃（bfq/hfq 各一次）"
    assert called == []
    assert len(issues) == 2, "每次丢弃都必须写 quality issue 告警"
    assert all(issue.kind == "backlog_expired" for issue in issues)
    assert all(issue.severity == "error" for issue in issues)
    assert all(issue.trade_date == old_date for issue in issues)
    assert all(issue.detail["age_days"] == 17 for issue in issues)
    assert all(issue.detail["max_age_days"] == 5 for issue in issues)
    assert conn.committed >= 2


def test_run_backlog_zero_max_age_disables_dropping(monkeypatch: pytest.MonkeyPatch) -> None:
    """0 = 明确关闭（不丢弃），非法值同样回退关闭。"""
    monkeypatch.setenv("BP_ETL_BACKLOG_MAX_AGE_DAYS", "0")
    conn = FakeConn()
    runner = FakeRunner(["000300"])
    now = datetime(2026, 11, 27, 16, 0, tzinfo=CN)
    orch = _orchestrator(monkeypatch, conn, runner, now=now)
    assert orch._backlog_max_age_days is None
    monkeypatch.setattr(orch_mod, "prune_backlog_symbols", lambda *a, **kw: 0)
    old_date = date(2026, 11, 10)
    monkeypatch.setattr(orch_mod, "due_backlog_dates", lambda c, n, a, now, limit=10: [old_date])
    monkeypatch.setattr(orch, "_db_coverage", lambda *a, **kw: 0.0)
    dropped: list = []
    monkeypatch.setattr(
        orch_mod, "clear_backlog",
        lambda c, dataset, trade_date, adjust, symbols=None: dropped.append(trade_date) or 9,
    )
    called: list = []
    monkeypatch.setattr(orch, "run_wave", lambda *a, **kw: called.append(kw))
    orch.run_backlog(now=now)
    assert dropped == []
    assert len(called) == 2


def test_db_coverage_filters_current_universe(monkeypatch: pytest.MonkeyPatch) -> None:
    conn = FakeConn(fetchone=[(1,)])
    runner = FakeRunner(["000300", "000905"])
    now = datetime(2026, 11, 27, 16, 0, tzinfo=CN)
    orch = _orchestrator(monkeypatch, conn, runner, now=now)
    coverage = orch._db_coverage(
        conn, runner.spec, D2, "bfq", 2, codes=["000300", "000905"]
    )
    assert coverage == pytest.approx(0.5)
    sql, params = conn.queries[-1]
    assert "ANY(%s)" in sql
    assert params[-1] == ["000300", "000905"]


def test_run_wave_syncs_freshness_state(monkeypatch: pytest.MonkeyPatch) -> None:
    from bp_api import freshness as freshness_mod

    conn = FakeConn(fetchone=[None, (42,)])
    runner = FakeRunner(["000300"])
    now = datetime(2026, 11, 27, 16, 0, tzinfo=CN)
    orch = _orchestrator(monkeypatch, conn, runner, now=now)
    monkeypatch.setattr(orch_mod, "write_bars", lambda *a, **kw: 1)
    monkeypatch.setattr(orch_mod, "refresh_coverage", lambda *a, **kw: 1)
    monkeypatch.setattr(orch_mod, "clear_backlog", lambda *a, **kw: 1)
    monkeypatch.setattr(orch, "_db_coverage", lambda *a, **kw: 1.0)
    monkeypatch.setattr(orch, "_db_present_symbols", lambda *a, **kw: {"000300"})
    recorded: list = []
    monkeypatch.setattr(
        freshness_mod, "record_freshness",
        lambda conn_, dataset, as_of, **kw: recorded.append((dataset, as_of, kw)) or True,
    )
    result = orch.run_wave("a_stock", "bfq", trade_date=D2, now=now, force=True)
    assert result.ok
    assert recorded, "数据集追平后应同步全局数据新鲜度"
    dataset, as_of, kwargs = recorded[0]
    assert dataset == "a_stock" and as_of == D2
    assert kwargs["status"] == "ok" and kwargs["source"] == "bp_etl"


# ---------------------------------------------------------------------------
# scripts/repair_quote_clean.py
# ---------------------------------------------------------------------------
def test_safe_sql_contains_backup_and_delete_guards() -> None:
    sql = rqc.safe_sql([date(2026, 11, 25), date(2026, 11, 26)])
    assert "bp_etl_backlog_bak_" in sql
    assert "DELETE FROM bp_etl_backlog" in sql
    assert "managed_by IS NULL" in sql
    assert "DATE '2026-11-25', DATE '2026-11-26'" in sql


def test_plan_backlog_reconcile_counts(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(rqc, "current_legacy_universe", lambda conn: ["000300", "HSI"])
    monkeypatch.setattr(
        rqc, "backlog_snapshot",
        lambda conn, dataset="legacy_index": {
            "total": 38252,
            "by_date": [(date(2026, 11, 25), 9434), (date(2026, 11, 26), 9496)],
        },
    )
    conn = FakeConn(fetchone=[(38000,), (18930,)])
    plan = rqc.plan_backlog_reconcile(
        conn, purge_dates=[date(2026, 11, 25), date(2026, 11, 26)]
    )
    assert plan["universe"] == 2
    assert plan["stale_symbol_rows"] == 38000
    assert plan["purge_rows"] == 18930


def test_apply_backlog_reconcile_calls_health_helpers(monkeypatch: pytest.MonkeyPatch) -> None:
    calls: list = []
    monkeypatch.setattr(rqc, "current_legacy_universe", lambda conn: ["000300"])
    monkeypatch.setattr(
        "bp_etl.health.prune_backlog_symbols",
        lambda c, dataset, adjust, keep: calls.append(("prune", dataset, adjust, tuple(keep))) or 10,
    )
    monkeypatch.setattr(
        "bp_etl.health.purge_backlog_dates",
        lambda c, dataset, adjust, dates: calls.append(("purge", dataset, adjust, tuple(dates))) or 3,
    )
    result = rqc.apply_backlog_reconcile(
        FakeConn(), purge_dates=[date(2026, 11, 25)]
    )
    assert result["removed_stale_symbol_rows"] == 20  # bfq+hfq 各 10
    assert result["removed_purge_date_rows"] == 6
    assert {item[0] for item in calls} == {"prune", "purge"}
    assert {item[2] for item in calls} == {"bfq", "hfq"}
