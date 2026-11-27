"""scripts/repair_quote_gaps.py 的 --dry-run 只读性（P2 回归）。

dry-run 必须：不写行情、不重建 clean、不刷新资产状态、不 record_freshness、
不 commit（也不能因为 --reconcile-backlog 而提前 return 跳过对账输出）。
"""
from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
_SPEC = importlib.util.spec_from_file_location(
    "repair_quote_gaps", ROOT / "scripts" / "repair_quote_gaps.py"
)
rqg = importlib.util.module_from_spec(_SPEC)
sys.modules["repair_quote_gaps"] = rqg
_SPEC.loader.exec_module(rqg)  # type: ignore[union-attr]


class _FakeConn:
    def __init__(self) -> None:
        self.commits = 0
        self.closed = False

    def commit(self) -> None:
        self.commits += 1

    def close(self) -> None:
        self.closed = True


def _run(monkeypatch: pytest.MonkeyPatch, argv: list[str]) -> _FakeConn:
    conn = _FakeConn()
    monkeypatch.setattr(rqg, "connect", lambda: conn)
    monkeypatch.setattr(sys, "argv", ["repair_quote_gaps.py", *argv])
    return conn


def test_dry_run_never_commits_or_records_freshness(monkeypatch: pytest.MonkeyPatch) -> None:
    conn = _run(monkeypatch, ["--dry-run", "--reconcile-backlog", "--date", "2026-11-27"])
    monkeypatch.setattr(rqg, "stale_pairs", lambda c, td: [])
    reconciled: list = []
    monkeypatch.setattr(rqg, "_reconcile_backlog", lambda c, dry_run: reconciled.append(dry_run))
    monkeypatch.setattr(
        rqg, "_record_freshness",
        lambda c: (_ for _ in ()).throw(AssertionError("dry-run 不得 record_freshness")),
    )
    assert rqg.main() == 0
    assert conn.commits == 0, "dry-run 不得 commit"
    assert conn.closed is True
    assert reconciled == [True], "dry-run 仍应执行 backlog 对账（只统计）"


def test_dry_run_reports_gap_but_does_not_fix(monkeypatch: pytest.MonkeyPatch) -> None:
    conn = _run(monkeypatch, ["--dry-run", "--date", "2026-11-27"])
    monkeypatch.setattr(rqg, "stale_pairs", lambda c, td: [("600519", "etf_em", None)])
    fixed: list = []
    monkeypatch.setattr(rqg, "bridge_etf", lambda *a, **kw: fixed.append(a) or True)
    monkeypatch.setattr(rqg, "fill_hkd", lambda *a, **kw: fixed.append("hkd") or True)
    monkeypatch.setattr(
        rqg, "_record_freshness",
        lambda c: (_ for _ in ()).throw(AssertionError("dry-run 不得 record_freshness")),
    )
    assert rqg.main() == 0
    assert fixed == [], "dry-run 只能报告 WOULD_FIX，不得执行修补"
    assert conn.commits == 0
