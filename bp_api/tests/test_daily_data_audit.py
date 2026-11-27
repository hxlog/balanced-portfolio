"""scripts/daily_data_audit.py 单元测试（纯 mock，不连库）。

覆盖：阈值与 registry 同口径、健康/异常报告与 exit code、落库行/issue 数量、
main 的 dry-run/apply 行为（stdout JSON）。
"""
from __future__ import annotations

import importlib.util
import json
import sys
from contextlib import contextmanager
from datetime import date
from pathlib import Path
from types import SimpleNamespace

import pytest

ROOT = Path(__file__).resolve().parents[2]
_SPEC = importlib.util.spec_from_file_location(
    "daily_data_audit", ROOT / "scripts" / "daily_data_audit.py"
)
ada = importlib.util.module_from_spec(_SPEC)
sys.modules["daily_data_audit"] = ada
_SPEC.loader.exec_module(ada)  # type: ignore[union-attr]

D = date(2026, 11, 27)


# ---------------------------------------------------------------------------
# 阈值 / make_check
# ---------------------------------------------------------------------------
def test_thresholds_match_registry() -> None:
    from bp_etl.registry import REGISTRY

    assert ada.COVERAGE_THRESHOLDS["a_stock"] == REGISTRY["a_stock"].coverage_min == 0.995
    assert ada.COVERAGE_THRESHOLDS["hk_stock"] == REGISTRY["hk_stock"].coverage_min == 0.97
    assert ada.COVERAGE_THRESHOLDS["etf"] == REGISTRY["etf"].coverage_min == 0.96
    assert ada.COVERAGE_THRESHOLDS["fund_nav"] == REGISTRY["fund_nav"].coverage_min == 0.90
    assert ada.COVERAGE_THRESHOLDS["index_quotes"] == 0.99
    assert ada.COVERAGE_THRESHOLDS["index_valuation"] == 0.99


def test_make_check_rules() -> None:
    assert ada.make_check("x", "coverage", 0.999, 0.99).status == "ok"
    assert ada.make_check("x", "coverage", 0.98, 0.99).status == "error"
    assert ada.make_check("x", "lag", 2, 0, rule="max").status == "error"
    assert ada.make_check("x", "lag", 0, 0, rule="max").status == "ok"
    # 缺失值：error 检查记 error，warn 检查记 warn（不误报 ok）
    assert ada.make_check("x", "coverage", None, 0.99).status == "error"
    assert ada.make_check("x", "accuracy", None, 0.05, severity="warn").status == "warn"


# ---------------------------------------------------------------------------
# audit()
# ---------------------------------------------------------------------------
def _patch_healthy(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(ada, "expected_trade_date", lambda conn, ref: D)
    monkeypatch.setattr(
        ada, "_lag_trading_days", lambda conn, as_of, expected: 0 if as_of else None
    )
    monkeypatch.setattr(ada, "load_dataset_state", lambda conn, ds, adj: D)
    monkeypatch.setattr(ada, "load_raw_max", lambda conn, ds, adj: D)
    monkeypatch.setattr(ada, "load_latest_run_coverage", lambda conn, ds, adj: (1.0, D))
    monkeypatch.setattr(ada, "load_prev_day_ratio", lambda conn, ds, adj, exp: 1.0)
    monkeypatch.setattr(
        ada, "load_index_quotes",
        lambda conn, exp: {"total": 10, "covered": 10, "as_of": D},
    )
    monkeypatch.setattr(
        ada, "load_index_valuation",
        lambda conn, exp: {"total": 10, "covered": 10, "as_of": D},
    )
    monkeypatch.setattr(ada, "load_table_max", lambda conn, sql: D)
    monkeypatch.setattr(
        ada, "load_clean_raw_lag",
        lambda conn: {"clean_max": D, "raw_max": D, "lag_days": 0},
    )
    monkeypatch.setattr(
        ada, "load_trading_year_coverage",
        lambda conn, reference=None, years=None: [
            {"year": 2026, "trading_days": 242, "calendar_days": 243,
             "ratio": 242 / 243, "ytd": True}
        ],
    )
    monkeypatch.setattr(
        ada, "load_accuracy",
        lambda conn, ds, exp: {
            "total": 100, "ohlc_bad": 0, "jump": 0, "jump_threshold_pct": 20.0
        },
    )
    monkeypatch.setattr(ada, "load_index_cross_source_bad_pairs", lambda conn, exp: 0)
    monkeypatch.setattr(
        ada, "load_pe_cross_source",
        lambda conn: {"max_rel_diff": 0.01, "samples": 10},
    )
    monkeypatch.setattr(ada, "load_backlog_total", lambda conn: 0)
    monkeypatch.setattr(ada, "load_freshness", lambda conn: {})


def test_audit_healthy_report(monkeypatch: pytest.MonkeyPatch) -> None:
    _patch_healthy(monkeypatch)
    report = ada.audit(object(), reference=D)
    assert report["stat_date"] == "2026-11-27"
    assert report["summary"]["total"] == len(report["checks"])
    assert report["summary"]["error"] == 0
    assert report["exit_code"] == 0
    metrics = {(check["dataset"], check["metric"]) for check in report["checks"]}
    for expected_metric in (
        ("a_stock", "coverage[bfq]"),
        ("hk_stock", "as_of_lag_trading_days[hfq]"),
        ("fund_nav", "coverage[nav]"),
        ("cffex", "as_of_lag_trading_days"),
        ("index_quotes", "coverage"),
        ("index_valuation", "coverage"),
        ("mvi", "as_of_lag_days"),
        ("clean", "clean_raw_lag_days"),
        ("index_valuation", "pe_cross_source_max_rel_diff"),
        ("backlog", "backlog_total"),
    ):
        assert expected_metric in metrics


def test_audit_flags_coverage_freshness_and_backlog(monkeypatch: pytest.MonkeyPatch) -> None:
    _patch_healthy(monkeypatch)
    monkeypatch.setattr(
        ada, "load_index_quotes",
        lambda conn, exp: {"total": 10, "covered": 5, "as_of": date(2026, 11, 20)},
    )
    monkeypatch.setattr(ada, "load_backlog_total", lambda conn: 5000)
    monkeypatch.setattr(ada, "load_clean_raw_lag", lambda conn: {
        "clean_max": date(2026, 11, 26), "raw_max": D, "lag_days": 1,
    })
    report = ada.audit(object(), reference=D)
    assert report["summary"]["error"] >= 3
    assert report["exit_code"] == 1
    by_key = {(check["dataset"], check["metric"]): check for check in report["checks"]}
    assert by_key[("index_quotes", "coverage")]["status"] == "error"
    assert by_key[("backlog", "backlog_total")]["status"] == "error"
    assert by_key[("clean", "clean_raw_lag_days")]["status"] == "error"


def test_trading_year_coverage_uses_cn_calendar_denominator(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """年度覆盖 = clean 落在 CN 交易日上的天数 / CN 交易日历天数（当年 YTD）。"""
    calls: list[tuple[str, tuple]] = []

    def fake_fetchall(conn, sql, params=()):
        calls.append((sql, tuple(params)))
        if "bp_quote_clean" in sql:
            # 分子必须 join CN 交易日历，剔除 7×24 源的周末/休市日行
            assert "bp_trading_calendar" in sql
            return [(2025, 200), (2026, 210)]
        assert "bp_trading_calendar" in sql
        return [(2025, 243), (2026, 220)]

    monkeypatch.setattr(ada, "_fetchall", fake_fetchall)
    items = ada.load_trading_year_coverage(object(), reference=D)
    by_year = {item["year"]: item for item in items}
    # 近 5 年：2022-2026（无日历数据的年份分母 0 -> 不判定）
    assert sorted(by_year) == [2022, 2023, 2024, 2025, 2026]
    assert by_year[2025]["trading_days"] == 200
    assert by_year[2025]["calendar_days"] == 243
    assert by_year[2025]["ratio"] == pytest.approx(200 / 243)
    assert by_year[2025]["ytd"] is False
    assert by_year[2026]["ratio"] == pytest.approx(210 / 220)
    assert by_year[2026]["ytd"] is True
    # 查询窗口：YTD 截止到 reference（不再按 date.today() 取全年）
    assert all(params[1] == D for _, params in calls)


def test_audit_flags_low_trading_year_coverage(monkeypatch: pytest.MonkeyPatch) -> None:
    """年度交易日覆盖低于 99.5% 必须 error（旧口径用固定 242 天会恒绿）。"""
    _patch_healthy(monkeypatch)
    monkeypatch.setattr(
        ada, "load_trading_year_coverage",
        lambda conn, reference=None, years=None: [
            {"year": 2025, "trading_days": 219, "calendar_days": 243,
             "ratio": 219 / 243, "ytd": False},
            {"year": 2026, "trading_days": 243, "calendar_days": 243,
             "ratio": 1.0, "ytd": True},
        ],
    )
    report = ada.audit(object(), reference=D)
    by_key = {(check["dataset"], check["metric"]): check for check in report["checks"]}
    bad = by_key[("clean", "trading_day_coverage_2025")]
    assert bad["status"] == "error"
    assert bad["value"] == pytest.approx(219 / 243)
    assert bad["threshold"] == pytest.approx(ada.TRADING_YEAR_COVERAGE_MIN) == 0.995
    assert bad["detail"]["trading_days"] == 219
    assert bad["detail"]["calendar_days"] == 243
    assert by_key[("clean", "trading_day_coverage_2026")]["status"] == "ok"
    assert report["exit_code"] == 1


# ---------------------------------------------------------------------------
# persist
# ---------------------------------------------------------------------------
class _PersistCursor:
    def __init__(self, conn: "_PersistConn") -> None:
        self.conn = conn

    def executemany(self, sql, rows) -> None:
        self.conn.executemany_calls.append((sql, list(rows)))

    def __enter__(self):
        return self

    def __exit__(self, *exc) -> bool:
        return False


class _PersistConn:
    def __init__(self) -> None:
        self.executemany_calls: list = []

    def cursor(self) -> _PersistCursor:
        return _PersistCursor(self)


def test_persist_writes_checks_and_issues(monkeypatch: pytest.MonkeyPatch) -> None:
    import bp_etl.health as health

    _patch_healthy(monkeypatch)
    monkeypatch.setattr(ada, "load_backlog_total", lambda conn: 5000)
    issues: list = []
    monkeypatch.setattr(health, "record_issues", lambda conn, items: issues.extend(items) or len(items))

    report = ada.audit(object(), reference=D)
    conn = _PersistConn()
    persisted = ada.persist(conn, report)
    assert persisted["rows_written"] == len(report["checks"])
    assert len(issues) == report["summary"]["warn"] + report["summary"]["error"]
    assert all(issue.kind.startswith("audit:") for issue in issues)
    sql, rows = conn.executemany_calls[0]
    assert "INSERT INTO bp_data_audit_daily" in sql
    assert len(rows) == len(report["checks"])


# ---------------------------------------------------------------------------
# main
# ---------------------------------------------------------------------------
class _MainConn:
    def __init__(self) -> None:
        self.autocommit = True
        self.commits = 0
        self.rollbacks = 0
        self.closed = False

    def commit(self) -> None:
        self.commits += 1

    def rollback(self) -> None:
        self.rollbacks += 1

    def close(self) -> None:
        self.closed = True


def _patch_main_db(monkeypatch: pytest.MonkeyPatch, conn: _MainConn) -> None:
    # main 在函数内 `from bp_ingest.config import load_config` /
    # `from bp_ingest.db import connect`，因此必须 patch 源模块属性
    # （patch ada._connect 不会被 main 使用，会连真实库）。
    import bp_ingest.config
    import bp_ingest.db

    monkeypatch.setattr(
        bp_ingest.config, "load_config", lambda: SimpleNamespace(db=object())
    )

    @contextmanager
    def fake_connect(db):
        try:
            yield conn
        finally:
            conn.close()

    monkeypatch.setattr(bp_ingest.db, "connect", fake_connect)


def _report(*, errors: int = 0) -> dict:
    status = "error" if errors else "ok"
    return {
        "stat_date": "2026-11-27",
        "reference_date": "2026-11-27",
        "generated_at": "2026-11-27T09:30:00+08:00",
        "datasets": list(ada.AUDIT_DATASETS),
        "checks": [
            {"dataset": "a_stock", "metric": "coverage[bfq]", "value": 0.5 if errors else 1.0,
             "threshold": 0.995, "status": status, "detail": {}},
        ],
        "summary": {"ok": 0 if errors else 1, "warn": 0, "error": errors, "total": 1},
        "exit_code": 1 if errors else 0,
    }


def test_main_dry_run_outputs_json_without_writing(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture
) -> None:
    conn = _MainConn()
    _patch_main_db(monkeypatch, conn)
    monkeypatch.setattr(ada, "audit", lambda c, reference=None: _report())
    monkeypatch.setattr(
        ada, "persist",
        lambda *a, **kw: (_ for _ in ()).throw(AssertionError("dry-run 不得写库")),
    )
    code = ada.main(["--dry-run", "--date", "2026-11-27"])
    assert code == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["exit_code"] == 0
    assert conn.commits == 0
    assert conn.closed is True


def test_main_apply_and_exit_1_on_error(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture
) -> None:
    conn = _MainConn()
    _patch_main_db(monkeypatch, conn)
    monkeypatch.setattr(ada, "audit", lambda c, reference=None: _report(errors=1))
    persisted: list = []
    monkeypatch.setattr(
        ada, "persist",
        lambda c, report: persisted.append(report) or {"rows_written": 1, "issues_written": 1},
    )
    code = ada.main(["--date", "2026-11-27"])
    assert code == 1
    assert conn.commits == 1
    assert persisted
    payload = json.loads(capsys.readouterr().out)
    assert payload["summary"]["error"] == 1


def test_main_writes_output_file(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, capsys: pytest.CaptureFixture
) -> None:
    conn = _MainConn()
    _patch_main_db(monkeypatch, conn)
    monkeypatch.setattr(ada, "audit", lambda c, reference=None: _report())
    monkeypatch.setattr(
        ada, "persist", lambda c, report: {"rows_written": 1, "issues_written": 0}
    )
    out = tmp_path / "audit.json"
    assert ada.main(["--date", "2026-11-27", "--output", str(out)]) == 0
    capsys.readouterr()
    assert json.loads(out.read_text(encoding="utf-8"))["stat_date"] == "2026-11-27"
