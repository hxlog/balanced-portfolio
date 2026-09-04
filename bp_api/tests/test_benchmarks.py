"""基准注册表与多腿合成测试(不依赖真实 PostgreSQL)。"""
from datetime import date

import numpy as np
import pandas as pd

from bp_api.repositories import BENCHMARKS, _compose_benchmark_series


def test_registry_contains_etf_benchmarks():
    for key, sym, name in [
        ("sp500_etf", "513500", "标普500ETF"),
        ("ndx100_etf", "513100", "纳斯达克100ETF"),
        ("n225_etf", "513520", "日经225ETF"),
    ]:
        spec = BENCHMARKS[key]
        assert spec["name"] == name
        assert spec["kind"] == "total_return"
        assert spec["legs"] == [(1.0, sym, "etf_em")]
        assert spec["note"]


def test_compose_two_leg_daily_rebalance():
    idx = [date(2024, 1, 2), date(2024, 1, 3), date(2024, 1, 4)]
    a = pd.Series([100.0, 110.0, 121.0], index=idx)   # +10%, +10%
    b = pd.Series([100.0, 100.0, 90.0], index=idx)    # 0%, -10%
    table = {("A", "s"): a, ("B", "s"): b}
    out = _compose_benchmark_series(
        [(0.6, "A", "s"), (0.4, "B", "s")], lambda sym, src: table[(sym, src)])
    assert out.iloc[0] == 1.0
    assert abs(out.iloc[1] - 1.06) < 1e-12              # 0.6*10% + 0.4*0%
    assert abs(out.iloc[2] - 1.06 * 1.02) < 1e-12       # 0.6*10% + 0.4*(-10%)


def test_compose_single_leg_equals_normalized_close():
    idx = [date(2024, 1, 2), date(2024, 1, 3)]
    s = pd.Series([200.0, 210.0], index=idx)
    out = _compose_benchmark_series([(1.0, "X", "s")], lambda sym, src: s)
    assert abs(out.iloc[1] - 1.05) < 1e-12


def test_compose_empty_leg_returns_empty():
    idx = [date(2024, 1, 2)]
    out = _compose_benchmark_series(
        [(0.5, "A", "s"), (0.5, "B", "s")],
        lambda sym, src: pd.Series([1.0], index=idx) if sym == "A" else pd.Series(dtype=float))
    assert out.empty


def test_compose_single_leg_gap_nan_zero_then_catchup():
    """单腿含中间 NaN(模拟 interp 缺口): 缺口日收益=0, 缺口收益归入复牌日(左锚 ffill 口径)。"""
    idx = [date(2024, 1, 2), date(2024, 1, 3), date(2024, 1, 4)]
    s = pd.Series([100.0, np.nan, 121.0], index=idx)
    out = _compose_benchmark_series([(1.0, "X", "s")], lambda sym, src: s)
    assert out.iloc[0] == 1.0
    assert out.iloc[1] == 1.0                      # 缺口日收益 = 0
    assert abs(out.iloc[2] - 1.21) < 1e-12         # 复牌日 = 真实缺口收益(+21%)
