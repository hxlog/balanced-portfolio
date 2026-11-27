"""scripts/backfill_legacy_quotes.py：legacy raw 回填（含 hfq）计划/执行/dry-run 测试。"""
from __future__ import annotations

import importlib.util
import json
import sys
from datetime import date
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
_SPEC = importlib.util.spec_from_file_location(
    "backfill_legacy_quotes", ROOT / "scripts" / "backfill_legacy_quotes.py"
)
bq = importlib.util.module_from_spec(_SPEC)
sys.modules["backfill_legacy_quotes"] = bq
_SPEC.loader.exec_module(bq)  # type: ignore[union-attr]

D = date(2026, 11, 27)
LAST = date(2026, 11, 24)


def _patch_configs(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        bq, "legacy_configs",
        lambda conn, symbols=None: [
            {"symbol": "510300", "source": "etf_em", "category": "etf",
             "adjust_modes": ("bfq", "hfq")},
            {"symbol": "000985", "source": "cn_index_em", "category": "index",
             "adjust_modes": ("bfq",)},
            {"symbol": "SPX", "source": "global_index_em", "category": "global",
             "adjust_modes": ("bfq",)},
        ],
    )
    monkeypatch.setattr(
        bq, "last_raw_date",
        lambda conn, symbol, source, adjust: LAST,
    )


def test_plan_providers_and_unsupported_skip(monkeypatch: pytest.MonkeyPatch) -> None:
    _patch_configs(monkeypatch)
    plans = bq.plan_backfill(object(), D)
    providers = {(plan["symbol"], plan["adjust"]): plan["provider"] for plan in plans}
    assert providers[("510300", "bfq")] == "v3_etf"
    assert providers[("510300", "hfq")] == "v3_etf"
    assert providers[("000985", "bfq")] == "free_index"
    assert providers[("SPX", "bfq")] == "unsupported"
    unsupported = next(plan for plan in plans if plan["provider"] == "unsupported")
    assert unsupported["reason"] == "no_free_source_for_market"
    # 起始日 = 库内最后日期 + 1
    first = next(plan for plan in plans if plan["symbol"] == "510300")
    assert first["start"] == "2026-11-25"

    # 已追平的标的不进计划
    monkeypatch.setattr(bq, "last_raw_date", lambda conn, symbol, source, adjust: D)
    assert bq.plan_backfill(object(), D) == []


def test_execute_plan_v3_etf_reanchors_to_legacy_close(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monitor = {}
    monkeypatch.setattr(
        bq, "load_v3_etf_rows",
        lambda conn, symbol, adjust, start, target: [
            (date(2026, 11, 25), 3.0, 3.1, 2.9, 3.0),
            (date(2026, 11, 26), 3.0, 3.2, 2.9, 3.1),
            (date(2026, 11, 27), 3.1, 3.3, 3.0, 3.2),
        ],
    )
    # 旧链 hfq 基准 = 4.0（v3 在 11-24 无行 -> 用 factor=1 无法锚定；这里同日起点 11-25，
    # 锚点 before=11-25 返回 11-22 收盘 4.0 且 v3 行无该日 -> factor=1，仅验证写出）。
    monkeypatch.setattr(bq, "load_legacy_anchor", lambda conn, *a, **kw: (date(2026, 11, 20), 4.0))
    plan = {
        "symbol": "510300", "source": "etf_em", "adjust": "hfq",
        "provider": "v3_etf", "start": "2026-11-25", "target": D.isoformat(),
        "market": None,
    }

    def writer(conn, rows):
        monitor["rows"] = list(rows)
        return len(rows)

    result = bq.execute_plan(object(), [plan], writer=writer)
    assert result["rows_written"] == 3
    assert result["plans_done"] == 1
    rows = monitor["rows"]
    assert {(row.symbol, row.source, row.adjust) for row in rows} == {
        ("510300", "etf_em", "hfq")
    }
    assert [row.trade_date for row in rows] == [
        date(2026, 11, 25), date(2026, 11, 26), D
    ]


def test_execute_plan_v3_etf_uses_overlap_factor(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        bq, "load_v3_etf_rows",
        lambda conn, symbol, adjust, start, target: [
            (date(2026, 11, 25), 2.0, 2.0, 2.0, 2.0),
            (date(2026, 11, 26), 2.0, 2.0, 2.0, 2.0),
        ],
    )
    # 旧链在 11-25 的 hfq 收盘 4.0；v3 同日 2.0 -> factor=2，写入 4.0
    monkeypatch.setattr(bq, "load_legacy_anchor", lambda conn, *a, **kw: (date(2026, 11, 25), 4.0))
    captured: list = []
    result = bq.execute_plan(
        object(),
        [{"symbol": "510300", "source": "etf_tx", "adjust": "hfq",
          "provider": "v3_etf", "start": "2026-11-25", "target": D.isoformat(),
          "market": None}],
        writer=lambda conn, rows: captured.extend(rows) or len(rows),
    )
    assert result["rows_written"] == 2
    assert captured[0].close == pytest.approx(4.0)


def test_execute_plan_free_index_and_skips(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        bq, "fetch_free_index_rows",
        lambda symbol, market, start, target, source=None: [
            {"trade_date": date(2026, 11, 25), "open": 1.0, "high": 1.1,
             "low": 0.9, "close": 1.05, "volume": None, "amount": None},
            {"trade_date": D, "open": 1.0, "high": 1.2,
             "low": 0.9, "close": 1.10, "volume": None, "amount": None},
        ],
    )
    monkeypatch.setattr(bq, "load_legacy_anchor", lambda conn, *a, **kw: (None, None))
    captured: list = []
    plans = [
        {"symbol": "000985", "source": "cn_index_em", "adjust": "hfq",
         "provider": "free_index", "start": "2026-11-25", "target": D.isoformat(),
         "market": "CSI"},
        {"symbol": "SPX", "source": "global_index_em", "adjust": "bfq",
         "provider": "unsupported", "start": "2026-11-25", "target": D.isoformat(),
         "market": None, "reason": "no_free_source_for_market"},
    ]
    result = bq.execute_plan(
        object(), plans, writer=lambda conn, rows: captured.extend(rows) or len(rows)
    )
    assert result["rows_written"] == 2
    # 指数不复权：hfq 口径同样写价格（adjust=hfq，源保留旧链 source）
    assert {(row.symbol, row.source, row.adjust) for row in captured} == {
        ("000985", "cn_index_em", "hfq")
    }
    assert {item["reason"] for item in result["skipped"]} == {
        "no_free_source_for_market"
    }


class _MainConn:
    def __init__(self) -> None:
        self.commits = 0
        self.rollbacks = 0
        self.closed = False

    def commit(self) -> None:
        self.commits += 1

    def rollback(self) -> None:
        self.rollbacks += 1

    def close(self) -> None:
        self.closed = True


def test_main_dry_run_does_not_write_or_commit(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture
) -> None:
    conn = _MainConn()
    monkeypatch.setattr(bq, "connect", lambda: conn)
    monkeypatch.setattr(bq, "target_trade_date", lambda c, ref: D)
    monkeypatch.setattr(bq, "plan_backfill", lambda *a, **kw: [{"symbol": "x"}])
    monkeypatch.setattr(
        bq, "execute_plan",
        lambda *a, **kw: (_ for _ in ()).throw(AssertionError("dry-run 不得写库")),
    )
    code = bq.main(["--date", "2026-11-27"])
    assert code == 0
    assert conn.commits == 0
    assert conn.rollbacks == 1
    payload = json.loads(capsys.readouterr().out)
    assert payload["apply"] is False
    assert payload["target_date"] == "2026-11-27"


def test_main_apply_writes_and_cleans(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture
) -> None:
    conn = _MainConn()
    plan = {"symbol": "510300", "provider": "v3_etf", "adjust": "hfq"}
    monkeypatch.setattr(bq, "connect", lambda: conn)
    monkeypatch.setattr(bq, "target_trade_date", lambda c, ref: D)
    monkeypatch.setattr(bq, "plan_backfill", lambda *a, **kw: [plan])
    monkeypatch.setattr(
        bq, "execute_plan", lambda c, plans: {"rows_written": 2, "plans_done": 1}
    )
    cleaned: list = []
    monkeypatch.setattr(
        bq, "rebuild_clean_for",
        lambda c, symbols: cleaned.append(list(symbols)) or {"symbols": 1},
    )
    assert bq.main(["--date", "2026-11-27", "--apply"]) == 0
    assert conn.commits == 1
    assert cleaned == [["510300"]]
    payload = json.loads(capsys.readouterr().out)
    assert payload["apply"] is True
    assert payload["applied"]["rows_written"] == 2
