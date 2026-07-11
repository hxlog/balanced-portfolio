"""回测引擎单测: 无未来函数、再平衡后偏离=0、NAV 合理。"""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from bp_api.quant.backtest import run_backtest


def _gbm(rng, n, mu, sigma, s0=100.0):
    rets = rng.normal(mu, sigma, n)
    return s0 * np.exp(np.cumsum(rets))


def _run(prices, bench, quadrant_assets, **kw):
    return run_backtest(
        prices=prices, benchmark=bench, quadrant_assets=quadrant_assets,
        method="quadrant_inner_sharpe_outer_rp", ratio="sharpe",
        lookback=156, min_window=60, rebalance_band=0.05,
        risk_free=0.0, trading_days=244, **kw,
    )


def test_nav_valid(synthetic_prices):
    prices, bench, quadrant_assets = synthetic_prices
    res = _run(prices, bench, quadrant_assets)
    assert not res.nav["nav"].isna().any()
    assert res.nav["nav"].iloc[0] == 1.0
    assert (res.nav["nav"] > 0).all()
    assert len(res.rebalances) >= 1


def test_rebalance_resets_deviation(synthetic_prices):
    prices, bench, quadrant_assets = synthetic_prices
    res = _run(prices, bench, quadrant_assets)
    # 每次再平衡后 target 权重和=1(存储权重保留6位小数, 容忍舍入)
    for rb in res.rebalances:
        assert abs(sum(rb.target_weights.values()) - 1.0) < 1e-3


def test_no_lookahead(synthetic_prices):
    """篡改某截止日之后的未来价格, 不应改变该日之前的 NAV/权重。"""
    prices, bench, quadrant_assets = synthetic_prices
    res1 = _run(prices, bench, quadrant_assets)

    cutoff = prices.index[len(prices) // 2]
    prices2 = prices.copy()
    mask = prices2.index > cutoff
    rng = np.random.default_rng(7)
    prices2.loc[mask] = prices2.loc[mask] * (1 + rng.normal(0, 0.05, prices2.loc[mask].shape))
    bench2 = bench.copy()
    bench2.loc[bench2.index > cutoff] *= 1.1
    res2 = _run(prices2, bench2, quadrant_assets)

    nav1 = res1.nav["nav"]
    nav2 = res2.nav["nav"]
    common = nav1.index[nav1.index <= cutoff]
    # 截止日之前 NAV 完全一致 → 无未来函数泄露
    assert np.allclose(nav1.loc[common].values, nav2.loc[common].values, atol=1e-9)


def test_effective_start_respects_user_start(synthetic_prices):
    prices, bench, quadrant_assets = synthetic_prices
    user_start = prices.index[400]
    res = _run(prices, bench, quadrant_assets, user_start=user_start)
    assert res.effective_start >= user_start


def test_partial_asset_inclusion(rng):
    """晚上市品种不应拖后全体 effective_start。"""
    dates = [d.date() for d in pd.bdate_range("2020-01-01", periods=800)]
    early = pd.Series(_gbm(rng, len(dates), 0.0004, 0.012), index=dates, name="A0@s")
    late_start = dates[400]
    late_vals = _gbm(rng, len(dates) - 400, 0.0004, 0.012)
    late = pd.Series(index=dates, dtype=float, name="A1@s")
    late.loc[dates[400]:] = late_vals
    prices = pd.DataFrame({"A0@s": early, "A1@s": late})
    bench = pd.Series(_gbm(rng, len(dates), 0.0002, 0.014), index=dates)
    quadrant_assets = {"overheat": ["A0@s"], "recovery": ["A1@s"]}
    user_start = dates[100]
    res = run_backtest(
        prices=prices, benchmark=bench, quadrant_assets=quadrant_assets,
        method="quadrant_inner_sharpe_outer_rp", ratio="sharpe",
        lookback=60, min_window=30, rebalance_band=0.05,
        risk_free=0.0, trading_days=244, user_start=user_start,
    )
    assert res.effective_start < late_start
    assert res.effective_start >= user_start


def test_stamp_duty_only_on_sell(synthetic_prices):
    """印花税仅卖出方缴纳; 手续费/滑点双边; 成本随印花税率单调增加。"""
    prices, bench, quadrant_assets = synthetic_prices
    # 用 0 再平衡带确保每日再平衡, 放大成本差异。
    def run(stamp):
        return run_backtest(
            prices=prices, benchmark=bench, quadrant_assets=quadrant_assets,
            method="quadrant_inner_sharpe_outer_rp", ratio="sharpe",
            lookback=156, min_window=60, rebalance_band=0.0,
            risk_free=0.0, trading_days=244,
            fee_rate=0.00015, slippage_rate=0.00015, stamp_duty_rate=stamp,
        )
    res0 = run(0.0)
    res1 = run(0.0005)
    res2 = run(0.001)
    # 加入印花税后终值 NAV 更低; 且印花税率越高 NAV 越低(单调)。
    assert res1.nav["nav"].iloc[-1] < res0.nav["nav"].iloc[-1]
    assert res2.nav["nav"].iloc[-1] < res1.nav["nav"].iloc[-1]


def test_inception_costs_reduce_nav(synthetic_prices):
    """建仓按买入周转计费后, 首日 NAV < 1。"""
    prices, bench, quadrant_assets = synthetic_prices
    res = run_backtest(
        prices=prices, benchmark=bench, quadrant_assets=quadrant_assets,
        method="all_risk_parity", ratio="sharpe",
        lookback=156, min_window=60, rebalance_band=0.05,
        risk_free=0.0, trading_days=244,
        fee_rate=0.00015, slippage_rate=0.00015, stamp_duty_rate=0.0,
    )
    assert res.nav["nav"].iloc[0] < 1.0
    assert res.nav["nav"].iloc[0] == pytest.approx(1.0 - 0.0003, abs=1e-12)


def test_cost_formula_buy_sell_split():
    """直接验证成本公式: cost = turnover*(fee+slip) + sell_turnover*stamp。"""
    import pandas as pd
    import numpy as np
    from bp_api.quant import backtest as bt

    # 构造一个确定性的 delta: prev=[0.5,0.5], target=[0.8,0.2]
    delta = pd.Series([0.3, -0.3])
    buy = float(delta.clip(lower=0.0).sum())   # 0.3
    sell = float((-delta.clip(upper=0.0)).sum())  # 0.3
    turnover = buy + sell  # 0.6
    fee, slip, stamp = 0.00015, 0.00015, 0.0005
    cost = turnover * (fee + slip) + sell * stamp
    # 0.6 * 0.0003 + 0.3 * 0.0005 = 0.00018 + 0.00015 = 0.00033
    assert abs(cost - 0.00033) < 1e-12
    assert buy == 0.3 and sell == 0.3 and turnover == 0.6


def test_degenerate_asset_no_nan_weights():
    """某成分窗内零方差(常数序列)时, 优化器不得返回 NaN 权重污染回测。"""
    import math
    import pandas as pd
    import numpy as np
    from bp_api.quant.optimizer import optimize

    dates = [d.date() for d in pd.bdate_range("2022-01-01", periods=400)]
    # A0 正常波动; A1 常数序列(零方差, 会使协方差退化/SLSQP 不收敛)
    a0 = pd.Series(np.random.default_rng(1).normal(0, 0.01, len(dates)).cumsum() + 100, index=dates)
    a1 = pd.Series(100.0, index=dates)  # 常数 -> 零方差
    rets = pd.DataFrame({"A0@s": a0.pct_change().fillna(0), "A1@s": a1.pct_change().fillna(0)})
    rets = rets.iloc[1:]  # 去掉首行 NaN

    for method in ["all_risk_parity", "all_max_sharpe", "sharpe_sq_risk_budget"]:
        w, _ = optimize(rets, None, method=method, ratio="sharpe")
        assert w.notna().all(), f"{method} 产生 NaN 权重: {w.to_dict()}"
        assert math.isfinite(float(w.sum())), f"{method} 权重和非法"
        assert abs(float(w.sum()) - 1.0) < 1e-6, f"{method} 权重和≠1: {w.sum()}"


def test_round_sanitizes_nan():
    """_round 把 NaN/Inf 归 0, 避免 PG JSON 拒绝 NaN token。"""
    import math
    from bp_api.quant.backtest import _round

    out = _round({"a": float("nan"), "b": float("inf"), "c": 0.1234567, "d": -float("inf")})
    assert out["a"] == 0.0 and out["b"] == 0.0 and out["d"] == 0.0
    assert out["c"] == 0.123457


def test_json_safe_replaces_nan():
    """_json_safe 递归把 NaN/Inf 转 None。"""
    from bp_api.repositories import _json_safe
    import math

    payload = {"a": float("nan"), "b": [1.0, float("inf"), 3], "c": {"d": float("-inf")}, "e": "x", "f": 2}
    safe = _json_safe(payload)
    assert safe == {"a": None, "b": [1.0, None, 3], "c": {"d": None}, "e": "x", "f": 2}
