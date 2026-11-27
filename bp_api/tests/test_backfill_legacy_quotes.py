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


def test_market_for_recognizes_h3_chinese_index_codes() -> None:
    """H3/H 开头的中证码必须先于 isdigit 识别，否则整条被当成 unsupported。"""
    assert bq._market_for("H30269", "csindex_oss") == "CSI"
    assert bq._market_for("H30007", "cn_index_em") == "CSI"
    assert bq._market_for("h30269", "csindex_perf") == "CSI"
    # 原有口径不变：港股指数 / 沪 / 深 / 中证数字码
    assert bq._market_for("HSTECH", "hk_index_em") == "HK"
    assert bq._market_for("HSTECH", "cn_index_em") is None
    assert bq._market_for("000985", "cn_index_em") == "CSI"
    assert bq._market_for("399006", "cn_index_em") == "SZ"
    assert bq._market_for("600519", "cn_index_em") == "SH"
    assert bq._market_for("SPX", "global_index_em") is None


def test_plan_h3_csi_codes_are_free_index(monkeypatch: pytest.MonkeyPatch) -> None:
    """27 个 H3 旧链标的不能再落到 unsupported（provider=free_index / market=CSI）。"""
    monkeypatch.setattr(
        bq, "legacy_configs",
        lambda conn, symbols=None: [
            {"symbol": "H30269", "source": "csindex_oss", "category": "index",
             "adjust_modes": ("bfq",)},
            {"symbol": "H30007", "source": "cn_index_em", "category": "index",
             "adjust_modes": ("hfq",)},
        ],
    )
    monkeypatch.setattr(bq, "last_raw_date", lambda conn, symbol, source, adjust: LAST)
    plans = bq.plan_backfill(object(), D)
    assert {plan["provider"] for plan in plans} == {"free_index"}
    assert {plan["market"] for plan in plans} == {"CSI"}
    assert all("reason" not in plan for plan in plans)


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
    """v3 无锚点日行：保持 factor=1，但必须记录 skip reason（不静默混基准）。"""
    monitor = {}
    monkeypatch.setattr(
        bq, "load_v3_etf_rows",
        lambda conn, symbol, adjust, start, target, **kw: [
            (date(2026, 11, 25), 3.0, 3.1, 2.9, 3.0),
            (date(2026, 11, 26), 3.0, 3.2, 2.9, 3.1),
            (date(2026, 11, 27), 3.1, 3.3, 3.0, 3.2),
        ],
    )
    # 旧链锚点 11-20 收盘 4.0，但 v3 无 11-20 行 -> 无重叠
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
    assert [item["reason"] for item in result["warnings"]] == ["v3_anchor_no_overlap"]
    rows = monitor["rows"]
    assert {(row.symbol, row.source, row.adjust) for row in rows} == {
        ("510300", "etf_em", "hfq")
    }
    assert [row.trade_date for row in rows] == [
        date(2026, 11, 25), date(2026, 11, 26), D
    ]
    # factor=1：原样写出 v3 收盘
    assert [row.close for row in rows] == pytest.approx([3.0, 3.1, 3.2])


def test_execute_plan_v3_etf_uses_overlap_factor(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """锚点日（< start）的 v3 重叠收盘参与重锚：factor=2，且锚点行不重复写出。"""
    monkeypatch.setattr(
        bq, "load_v3_etf_rows",
        lambda conn, symbol, adjust, start, target, **kw: [
            (date(2026, 11, 24), 2.0, 2.0, 2.0, 2.0),  # 锚点日（旧链最后一日）
            (date(2026, 11, 25), 2.0, 2.0, 2.0, 2.0),
            (date(2026, 11, 26), 2.1, 2.1, 2.1, 2.1),
        ],
    )
    # 旧链在 11-24 的 hfq 收盘 4.0；v3 同日 2.0 -> factor=2
    monkeypatch.setattr(bq, "load_legacy_anchor", lambda conn, *a, **kw: (date(2026, 11, 24), 4.0))
    captured: list = []
    result = bq.execute_plan(
        object(),
        [{"symbol": "510300", "source": "etf_tx", "adjust": "hfq",
          "provider": "v3_etf", "start": "2026-11-25", "target": D.isoformat(),
          "market": None}],
        writer=lambda conn, rows: captured.extend(rows) or len(rows),
    )
    assert result["rows_written"] == 2
    assert result["warnings"] == []
    assert [row.trade_date for row in captured] == [
        date(2026, 11, 25), date(2026, 11, 26)
    ]
    assert [row.close for row in captured] == pytest.approx([4.0, 4.2])
    # 锚点日行只用于对齐基准，不重复写出
    assert date(2026, 11, 24) not in {row.trade_date for row in captured}


class _V3Cursor:
    def __init__(self, conn: "_V3Conn") -> None:
        self.conn = conn

    def execute(self, sql, params=None) -> None:
        self.conn.statements.append((sql, params))

    def fetchall(self) -> list:
        return list(self.conn.rows)

    def __enter__(self):
        return self

    def __exit__(self, *exc) -> bool:
        return False


class _V3Conn:
    def __init__(self, rows) -> None:
        self.rows = list(rows)
        self.statements: list = []

    def cursor(self) -> _V3Cursor:
        return _V3Cursor(self)


def test_dedupe_v3_rows_keeps_single_source_no_basis_mixing() -> None:
    """同一天多源不能逐日混用（:factor 与锚定源绝对基价不同），整段只取一个源。"""
    earlier = date(2026, 11, 23)
    day = date(2026, 11, 24)
    later = date(2026, 11, 25)
    rows = [
        # 因子源覆盖更长（优先覆盖），但优先级低；锚定源仅锚点日有行
        (earlier, 1.0, 1.0, 1.0, 1.130, "sina_etf_kline:factor"),
        (day, 1.0, 1.0, 1.0, 1.131616, "sina_etf_kline:factor"),
        (later, 1.0, 1.0, 1.0, 1.130, "sina_etf_kline:factor"),
        (day, 1.0, 1.0, 1.0, 1.145, "tencent_etf_kline"),
    ]
    assert bq.dedupe_v3_rows(rows, day) == [
        (earlier, 1.0, 1.0, 1.0, 1.130),
        (day, 1.0, 1.0, 1.0, 1.131616),
        (later, 1.0, 1.0, 1.0, 1.130),
    ]


def test_select_v3_source_prefers_anchor_overlap_then_priority() -> None:
    anchor = date(2026, 11, 24)
    # 锚点日有重叠的源优先（否则无法重锚），即使另一源覆盖更长
    rows = [
        (date(2026, 11, 20), 1.0, 1.0, 1.0, 1.0, "sina_etf_kline:factor"),
        (date(2026, 11, 21), 1.0, 1.0, 1.0, 1.0, "sina_etf_kline:factor"),
        (date(2026, 11, 22), 1.0, 1.0, 1.0, 1.0, "sina_etf_kline:factor"),
        (anchor, 1.0, 1.0, 1.0, 1.0, "tencent_etf_kline"),
    ]
    assert bq.select_v3_source(rows, anchor) == "tencent_etf_kline"
    # 同覆盖行数时按固定优先级（tencent_etf_kline > tencent_kline > em_kline）
    tie = [
        (anchor, 1.0, 1.0, 1.0, 1.0, "em_kline"),
        (anchor, 1.0, 1.0, 1.0, 1.0, "tencent_kline"),
        (date(2026, 11, 25), 1.0, 1.0, 1.0, 1.0, "em_kline"),
        (date(2026, 11, 25), 1.0, 1.0, 1.0, 1.0, "tencent_kline"),
    ]
    assert bq.select_v3_source(tie, anchor) == "tencent_kline"
    # 无锚点日时按覆盖行数降序（覆盖长的源优先）
    coverage = [
        (anchor, 1.0, 1.0, 1.0, 1.0, "em_kline"),
        (date(2026, 11, 25), 1.0, 1.0, 1.0, 1.0, "tencent_etf_kline"),
        (date(2026, 11, 26), 1.0, 1.0, 1.0, 1.0, "tencent_etf_kline"),
    ]
    assert bq.select_v3_source(coverage, None) == "tencent_etf_kline"


def test_load_v3_etf_rows_selects_source_and_passes_anchor_date() -> None:
    day = date(2026, 11, 24)
    conn = _V3Conn(
        [
            (day, 1.0, 1.0, 1.0, 2.1, "em_kline"),
            (day, 1.0, 1.0, 1.0, 2.0, "tencent_kline"),
        ]
    )
    rows = bq.load_v3_etf_rows(
        conn, "510300", "hfq", day, D, anchor_date=day
    )
    assert rows == [(day, 1.0, 1.0, 1.0, 2.0)]
    sql = conn.statements[-1][0]
    assert "source" in sql, "必须查询 source 才能按固定源去重"


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


def test_execute_plan_free_index_fills_h3_code(monkeypatch: pytest.MonkeyPatch) -> None:
    """H3 中证码走免费源降级链回填（source 保留旧链口径）。"""
    monkeypatch.setattr(
        bq, "fetch_free_index_rows",
        lambda symbol, market, start, target, source=None: [
            {"trade_date": date(2026, 11, 25), "open": 1.0, "high": 1.1,
             "low": 0.9, "close": 1.05, "volume": None, "amount": None},
            {"trade_date": D, "open": 1.0, "high": 1.2,
             "low": 0.9, "close": 1.10, "volume": None, "amount": None},
        ]
        if market == "CSI"
        else [],
    )
    monkeypatch.setattr(bq, "load_legacy_anchor", lambda conn, *a, **kw: (None, None))
    captured: list = []
    result = bq.execute_plan(
        object(),
        [{"symbol": "H30269", "source": "csindex_oss", "adjust": "bfq",
          "provider": "free_index", "start": "2026-11-25",
          "target": D.isoformat(), "market": "CSI"}],
        writer=lambda conn, rows: captured.extend(rows) or len(rows),
    )
    assert result["rows_written"] == 2
    assert {(row.symbol, row.source, row.adjust) for row in captured} == {
        ("H30269", "csindex_oss", "bfq")
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
