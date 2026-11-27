"""scripts/compute_fund_risk.py：净值口径 / 断点检测 / 基准口径 / 全量重算编排。

不连数据库：数据访问用 FakeConn 打桩；被测逻辑为脚本内纯函数 + recompute_all。
关键回归（2026-11-27 HSI TE 修复）：
- 用 513660 类样本（单位净值含份额拆分、累计净值连续）验证
  新口径 TE 约 4.3%（正确量级），旧 nav 口径 TE 约 50%（对应生产 50.57% 事故值）。
"""
from __future__ import annotations

import importlib.util
import math
import sys
from datetime import date
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

ROOT = Path(__file__).resolve().parents[2]
_SPEC = importlib.util.spec_from_file_location(
    "compute_fund_risk", ROOT / "scripts" / "compute_fund_risk.py"
)
fr = importlib.util.module_from_spec(_SPEC)
sys.modules["compute_fund_risk"] = fr  # dataclass 需要 cls.__module__ 可在 sys.modules 找到
_SPEC.loader.exec_module(fr)  # type: ignore[union-attr]

BDATES = pd.bdate_range("2025-01-02", periods=400)
SPLIT_POS = 280  # 最后 252 个收益窗口内，保证旧 nav 口径的 TE 被拆分污染


def _market(seed: int = 7):
    """合成 513660 类样本：HSI 价格 + HKDCNY，累计净值 = 基准 + 4.3% 量级噪声。"""
    rng = np.random.default_rng(seed)
    price = pd.Series(25000 * np.exp(np.cumsum(rng.normal(0.0003, 0.0115, len(BDATES)))), index=BDATES)
    fx = pd.Series(0.91 * np.exp(np.cumsum(rng.normal(0.0, 0.0014, len(BDATES)))), index=BDATES)
    price_ret = price.pct_change().dropna()
    fx_ret = fx.pct_change().dropna()
    bench_ret = fr.apply_fx(price_ret, fx_ret)
    noise = rng.normal(0.0, 0.043 / math.sqrt(252), len(bench_ret))
    acc = pd.Series(np.cumprod(1.0 + (bench_ret + noise).to_numpy()), index=bench_ret.index)
    # 单位净值：2026-04 类份额拆分，拆分前单位净值是累计净值的 2 倍
    factor = np.where(np.arange(len(acc)) < SPLIT_POS, 2.0, 1.0)
    unit_nav = pd.Series(acc.to_numpy() * factor, index=acc.index)
    return {
        "price": price,
        "fx": fx,
        "bench_ret": bench_ret,
        "acc": acc,
        "unit_nav": unit_nav,
        "dates": [d.date() for d in BDATES],
    }


# ---------------------------------------------------------------------------
# 代码归一 / 断点检测
# ---------------------------------------------------------------------------
def test_normalize_etf_code_strips_venue_prefix():
    assert fr.normalize_etf_code("SH513660") == "513660"
    assert fr.normalize_etf_code("SZ159920") == "159920"
    assert fr.normalize_etf_code("OF000001") == "000001"
    assert fr.normalize_etf_code("513660") == "513660"


def test_repair_level_shift_keeps_series_continuous_and_returns_preserved():
    m = _market()
    acc = m["acc"]
    values = acc.to_numpy(copy=True)
    values[SPLIT_POS:] /= 2.0  # 水平跳变：拆分未在 acc 口径中体现
    broken = pd.Series(values, index=acc.index)

    repaired, events = fr.detect_and_repair_breaks(broken)
    assert len(events) == 1
    event = events[0]
    assert event.kind == "level_shift"
    assert event.factor == pytest.approx(0.5, abs=0.01)
    # 修复后无 >30% 单日跳变；断点前段内部收益不变
    assert float(repaired.pct_change().abs().max()) < 0.10
    before = min(SPLIT_POS, len(repaired) - 1)
    orig_ret = broken.pct_change().iloc[: before - 1].dropna()
    fixed_ret = repaired.pct_change().iloc[: min(before, len(repaired)) - 1].dropna()
    common = orig_ret.index.intersection(fixed_ret.index)
    assert np.allclose(orig_ret.loc[common].to_numpy(), fixed_ret.loc[common].to_numpy())


def test_repair_spike_removes_bad_print():
    acc = _market()["acc"]
    values = acc.to_numpy(copy=True)
    spike_pos = 200
    values[spike_pos] *= 1.9
    spiked = pd.Series(values, index=acc.index)

    repaired, events = fr.detect_and_repair_breaks(spiked)
    assert len(events) == 1 and events[0].kind == "spike_removed"
    assert len(repaired) == len(spiked) - 1
    assert float(repaired.pct_change().abs().max()) < 0.10


def test_repair_clean_series_untouched():
    acc = _market()["acc"]
    repaired, events = fr.detect_and_repair_breaks(acc)
    assert events == []
    assert len(repaired) == len(acc)
    assert np.allclose(repaired.to_numpy(), acc.to_numpy())


def test_detect_nav_splits_flags_unit_nav_break_with_continuous_acc():
    m = _market()
    events = fr.detect_nav_splits(m["unit_nav"], m["acc"])
    assert len(events) == 1
    assert events[0].kind == "nav_split_ignored"
    assert events[0].raw_return == pytest.approx(-0.5, abs=0.01)


# ---------------------------------------------------------------------------
# 净值口径选择
# ---------------------------------------------------------------------------
def test_pick_fund_series_prefers_acc_nav():
    m = _market()
    picked = fr.pick_fund_series(m["unit_nav"], m["acc"], None)
    assert picked is not None and picked.basis == fr.NAV_BASIS_ACC
    assert len(picked.cross_check_events) == 1


def test_pick_fund_series_falls_back_to_etf_hfq():
    m = _market()
    picked = fr.pick_fund_series(m["unit_nav"], pd.Series(dtype=float), m["acc"] * 1.3)
    assert picked is not None and picked.basis == fr.NAV_BASIS_ETF


def test_pick_fund_series_last_resort_is_nav():
    m = _market()
    picked = fr.pick_fund_series(m["unit_nav"], pd.Series(dtype=float), None)
    assert picked is not None and picked.basis == fr.NAV_BASIS_NAV


def test_pick_fund_series_none_when_too_short():
    short = pd.Series([1.0, 1.1, 1.2], index=BDATES[:3])
    assert fr.pick_fund_series(short, pd.Series(dtype=float), None) is None


# ---------------------------------------------------------------------------
# 核心回归：513660 类样本新口径 TE≈4.3%，旧 nav 口径≈50%
# ---------------------------------------------------------------------------
def test_513660_like_tracking_error_new_caliber_about_4_3_pct():
    m = _market()
    new_metrics = fr.compute_fund_metrics(m["acc"], m["bench_ret"])
    assert new_metrics is not None
    te = new_metrics["tracking_error_1y"]
    assert te == pytest.approx(4.3, abs=0.5), f"新口径 TE={te}（期望 ~4.3%）"

    old_metrics = fr.compute_fund_metrics(m["unit_nav"], m["bench_ret"])
    assert old_metrics is not None
    old_te = old_metrics["tracking_error_1y"]
    assert 40.0 < old_te < 60.0, f"旧 nav 口径 TE={old_te}（期望 ~50%）"


def test_513660_like_full_pipeline_repairs_split_and_reports_basis():
    m = _market()
    nav_rows = pd.DataFrame(
        {
            "fund_code": "SH513660",
            "trade_date": m["acc"].index,
            "nav": m["unit_nav"].to_numpy(),
            "acc_nav": m["acc"].to_numpy(),
        }
    )
    benchmarks = {
        "HSI": fr.Benchmark(
            code="HSI", returns=m["bench_ret"], basis=fr.BENCHMARK_BASIS_HSI_FX
        )
    }
    rows, stats = fr.build_risk_rows(
        nav_rows, {}, {"SH513660": "HSI"}, benchmarks
    )
    assert len(rows) == 1
    row = rows[0]
    assert row["benchmark_code"] == "HSI"
    assert row["tracking_error_1y"] == pytest.approx(4.3, abs=0.5)
    assert stats["nav_basis_counts"] == {"acc_nav": 1}
    assert stats["benchmark_basis_counts"] == {"hsi_price_x_hkdcny": 1}
    # 交叉记录：单位净值拆分但累计净值连续（旧 nav 口径的事故来源）
    assert any(e["kind"] == "nav_split_ignored" for e in stats["nav_split_events"])


# ---------------------------------------------------------------------------
# 基准口径
# ---------------------------------------------------------------------------
def test_apply_fx_compounds_returns_on_price_dates():
    price_ret = pd.Series([0.01, -0.02, 0.03], index=BDATES[:3])
    fx_ret = pd.Series([0.001, 0.002, -0.001], index=BDATES[:3])
    out = fr.apply_fx(price_ret, fx_ret)
    expected = [(1.01 * 1.001 - 1), (0.98 * 1.002 - 1), (1.03 * 0.999 - 1)]
    assert np.allclose(out.to_numpy(), expected)


def test_combine_benchmark_returns_basis_switches():
    price_ret = pd.Series([0.01, 0.02], index=BDATES[:2])
    fx_ret = pd.Series([0.001, 0.0], index=BDATES[:2])

    ret_price, basis_price = fr.combine_benchmark_returns(price_ret, fx_ret=fx_ret, hsi_mode="price")
    assert basis_price == fr.BENCHMARK_BASIS_PRICE
    assert np.allclose(ret_price.to_numpy(), price_ret.to_numpy())

    ret_fx, basis_fx = fr.combine_benchmark_returns(price_ret, fx_ret=fx_ret, hsi_mode="auto")
    assert basis_fx == fr.BENCHMARK_BASIS_HSI_FX
    assert not np.allclose(ret_fx.to_numpy(), price_ret.to_numpy())

    ret_tr, basis_tr = fr.combine_benchmark_returns(
        price_ret, fx_ret=fx_ret, has_total_return=True, hsi_mode="auto"
    )
    assert basis_tr == fr.BENCHMARK_BASIS_HSI_TR
    assert np.allclose(ret_tr.to_numpy(), price_ret.to_numpy())


# ---------------------------------------------------------------------------
# recompute_all 编排（FakeConn，不连库）
# ---------------------------------------------------------------------------
class _FakeCursor:
    def __init__(self, conn: "_FakeConn") -> None:
        self.conn = conn
        self._rows: list = []
        self.rowcount = 0

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def execute(self, sql: str, params=None) -> None:
        text = " ".join(str(sql).split())
        self.conn.queries.append((text, params))
        if text.startswith("WITH last_fund_date"):
            self._rows = self.conn.primary_rows
        elif "FROM bp_fund_nav_daily" in text:
            self._rows = self.conn.nav_rows
        elif "FROM bp_etf_quote_daily" in text:
            self._rows = self.conn.etf_rows
        elif "HAVING count(*) > 100" in text:
            self._rows = self.conn.total_return_rows
        elif (
            isinstance(params, (list, tuple))
            and params
            and isinstance(params[0], str)
            and params[0] == "HSI_TR"
        ):
            self._rows = self.conn.tr_rows
        elif "source = 'fx_sina'" in text:
            self._rows = self.conn.fx_rows
        elif "bp_index_quote_daily" in text:
            self._rows = self.conn.bench_rows
        elif text.startswith("DELETE FROM bp_fund_risk"):
            self.conn.deletes.append((text, params))
            self._rows = []
            self.rowcount = 5
            return
        else:
            self._rows = []
        self.rowcount = len(self._rows)

    def executemany(self, sql: str, payload) -> None:
        items = list(payload)
        self.conn.upserts.append((" ".join(str(sql).split()), items))
        self.rowcount = len(items)

    def fetchone(self):
        return self._rows[0] if self._rows else None

    def fetchall(self) -> list:
        return self._rows


class _FakeConn:
    def __init__(self) -> None:
        self.primary_rows: list = []
        self.nav_rows: list = []
        self.etf_rows: list = []
        self.bench_rows: list = []
        self.fx_rows: list = []
        self.total_return_rows: list = []
        self.tr_rows: list = []
        self.queries: list = []
        self.upserts: list = []
        self.deletes: list = []
        self.commits = 0

    def cursor(self):
        return _FakeCursor(self)

    def commit(self) -> None:
        self.commits += 1


def _recompute_fake_conn() -> _FakeConn:
    m = _market()
    conn = _FakeConn()
    conn.primary_rows = [("SH513660", "HSI")]
    nav_index = m["acc"].index  # 累计净值/单位净值序列的日期（400 个价格 -> 399 个收益）
    conn.nav_rows = [
        ("SH513660", day.date(), float(nav), float(acc))
        for day, nav, acc in zip(nav_index, m["unit_nav"].to_numpy(), m["acc"].to_numpy())
    ]
    price_index = m["price"].index
    conn.bench_rows = [
        ("HSI", day.date(), float(close))
        for day, close in zip(price_index, m["price"].to_numpy())
    ]
    conn.fx_rows = [
        ("HKDCNY", day.date(), float(close))
        for day, close in zip(price_index, m["fx"].to_numpy())
    ]
    return conn


def test_recompute_all_writes_upsert_with_hsi_fx_basis():
    conn = _recompute_fake_conn()
    summary = fr.recompute_all(conn, batch_size=10)

    assert summary["universe_size"] == 1
    assert summary["funds_computed"] == 1
    assert summary["rows_written"] == 1
    assert summary["nav_basis_counts"] == {"acc_nav": 1}
    assert summary["benchmark_basis_counts"] == {"hsi_price_x_hkdcny": 1}
    assert conn.commits >= 1
    assert len(conn.upserts) == 1
    sql, payload = conn.upserts[0]
    assert "INSERT INTO bp_fund_risk" in sql and "ON CONFLICT (fund_code)" in sql
    row = payload[0]
    assert row["fund_code"] == "SH513660"
    assert row["benchmark_code"] == "HSI"
    assert row["tracking_error_1y"] == pytest.approx(4.3, abs=0.5)
    assert isinstance(row["as_of"], date)
    # 输出汇总可 JSON 序列化（--report 依赖）
    import json

    json.dumps(summary, ensure_ascii=False, default=str)


def test_recompute_all_dry_run_does_not_write():
    conn = _recompute_fake_conn()
    summary = fr.recompute_all(conn, batch_size=10, dry_run=True)
    assert summary["rows_written"] == 0
    assert conn.upserts == []
    assert summary["funds_computed"] == 1


def test_recompute_all_rejects_unknown_hsi_mode():
    with pytest.raises(ValueError):
        fr.recompute_all(_FakeConn(), hsi_mode="bogus")


def test_load_benchmark_returns_prefers_total_return_when_available():
    m = _market()
    conn = _recompute_fake_conn()
    conn.total_return_rows = [("HSI_TR",)]
    conn.tr_rows = [
        ("HSI_TR", day.date(), float(close))
        for day, close in zip(m["price"].index, m["price"].to_numpy())
    ]
    benchmarks = fr.load_benchmark_returns(conn, ["HSI"], hsi_mode="auto")
    assert benchmarks["HSI"].basis == fr.BENCHMARK_BASIS_HSI_TR
    tr_frame = pd.DataFrame(conn.tr_rows, columns=["symbol", "trade_date", "close"])
    expected = fr._to_return_series(fr._frame_to_series(tr_frame, "HSI_TR"))
    assert benchmarks["HSI"].returns.equals(expected)
    assert len(benchmarks["HSI"].returns) > 100


def test_load_benchmark_returns_price_mode_ignores_tr():
    conn = _recompute_fake_conn()
    conn.total_return_rows = [("HSI_TR",)]
    benchmarks = fr.load_benchmark_returns(conn, ["HSI"], hsi_mode="price")
    assert benchmarks["HSI"].basis == fr.BENCHMARK_BASIS_PRICE


def test_recompute_all_prune_deletes_rows_outside_universe():
    conn = _recompute_fake_conn()
    summary = fr.recompute_all(conn, batch_size=10, prune=True)
    assert summary["pruned"] == 5
    assert len(conn.deletes) == 1
    assert "DELETE FROM bp_fund_risk" in conn.deletes[0][0]
    assert conn.deletes[0][1][0][0] == "SH513660"
