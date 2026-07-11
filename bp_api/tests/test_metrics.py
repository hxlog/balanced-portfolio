"""绩效指标单测。"""

from __future__ import annotations

import numpy as np
import pandas as pd

from bp_api.quant.metrics import compute_metrics, max_drawdown, max_drawdown_recovery_days


def test_max_drawdown():
    nav = pd.Series([1.0, 1.2, 0.9, 1.1], index=pd.bdate_range("2024-01-01", periods=4).date)
    # 峰值 1.2 → 谷 0.9, 回撤 = 0.9/1.2-1 = -0.25
    assert abs(max_drawdown(nav) - (-0.25)) < 1e-9


def test_metrics_keys_and_ranges():
    dates = pd.bdate_range("2022-01-01", periods=300).date
    rng = np.random.default_rng(1)
    nav = pd.Series(np.cumprod(1 + rng.normal(0.0005, 0.01, 300)), index=dates)
    m = compute_metrics(nav, None, risk_free=0.0, trading_days=244)
    for k in ["sharpe", "sortino", "calmar", "max_drawdown", "max_drawdown_recovery_days",
              "annualized_return", "annualized_vol", "period_returns", "period_vols"]:
        assert k in m
    assert m["max_drawdown"] <= 0
    assert "annualized" in m["period_returns"]
    assert "1y" in m["period_returns"]


def test_max_drawdown_recovery_days():
    dates = pd.bdate_range("2022-01-01", periods=10).date
    nav = pd.Series([1.0, 0.85, 0.80, 0.82, 0.90, 1.01, 1.05], index=dates[:7])
    assert max_drawdown_recovery_days(nav) == 3  # trough idx 2 -> recovery idx 5


def test_max_drawdown_recovery_days_not_recovered():
    dates = pd.bdate_range("2022-01-01", periods=5).date
    nav = pd.Series([1.0, 0.9, 0.7, 0.72, 0.75], index=dates)
    assert max_drawdown_recovery_days(nav) is None


def test_information_ratio_present_with_benchmark():
    dates = pd.bdate_range("2022-01-01", periods=300).date
    rng = np.random.default_rng(2)
    nav = pd.Series(np.cumprod(1 + rng.normal(0.0006, 0.01, 300)), index=dates)
    bench = pd.Series(np.cumprod(1 + rng.normal(0.0002, 0.012, 300)), index=dates)
    m = compute_metrics(nav, bench, risk_free=0.0, trading_days=244)
    assert m["information_ratio"] is not None
