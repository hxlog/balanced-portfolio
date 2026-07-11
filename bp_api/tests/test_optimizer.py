"""优化器单测: 约束、ERC 风险贡献相等、象限法结构。"""

from __future__ import annotations

import numpy as np

from bp_api.quant.optimizer import optimize, risk_parity_weights


def _risk_contributions(w, cov):
    vol = np.sqrt(w @ cov @ w)
    return w * (cov @ w) / vol


def test_weights_sum_to_one_and_long_only(synthetic_returns):
    for method in ["all_risk_parity", "all_max_sharpe", "sharpe_sq_risk_budget"]:
        w, _ = optimize(synthetic_returns, method=method)
        assert abs(w.sum() - 1.0) < 1e-6
        assert (w >= -1e-9).all()


def test_risk_parity_equal_contribution(synthetic_returns):
    cov = synthetic_returns.cov().values
    w = risk_parity_weights(cov)
    rc = _risk_contributions(w, cov)
    # 各资产风险贡献应近似相等(SLSQP 数值解, 容忍小幅离散)
    assert rc.std() / rc.mean() < 0.15


def test_max_weight_cap(synthetic_returns):
    w, _ = optimize(synthetic_returns, method="all_max_sharpe", max_weight=0.3)
    assert w.max() <= 0.3 + 1e-6
    assert abs(w.sum() - 1.0) < 1e-6


def test_quadrant_method_structure(synthetic_returns):
    q_assets = {
        "overheat": ["A0", "A1"],
        "stagflation": ["A2"],
        "recovery": ["A3"],
        "recession": ["A4"],
    }
    w, quad = optimize(synthetic_returns, quadrant_assets=q_assets,
                       method="quadrant_inner_sharpe_outer_rp")
    assert abs(w.sum() - 1.0) < 1e-6
    assert quad is not None
    assert abs(sum(quad.values()) - 1.0) < 1e-6
    # 单象限资产时, 象限外层权重 = 该象限内各资产最终权重之和
    assert abs((w["A0"] + w["A1"]) - quad["overheat"]) < 1e-6


def test_multi_quadrant_weight_aggregation(synthetic_returns):
    """同一资产跨象限时, 最终权重为各象限贡献之和。"""
    cols = ["A0", "A1", "A2"]
    q_assets = {
        "overheat": ["A0", "A1"],
        "recession": ["A0", "A2"],
    }
    w, quad = optimize(
        synthetic_returns[cols], quadrant_assets=q_assets,
        method="quadrant_inner_sharpe_outer_rp",
    )
    assert abs(w.sum() - 1.0) < 1e-6
    assert w["A0"] > 0
    assert abs(quad["overheat"] + quad["recession"] - 1.0) < 1e-6


def test_sortino_runs(synthetic_returns):
    w, _ = optimize(synthetic_returns, method="all_max_sharpe", ratio="sortino")
    assert abs(w.sum() - 1.0) < 1e-6


def test_singular_cov_does_not_nan():
    """病态/奇异协方差(完全共线 + 零方差)下, 优化器不得产出 NaN, 权重和=1。
    验证 _regularize_cov(Ledoit-Wolf 收缩 + Ridge)治本: 求解器拿到良态矩阵。"""
    import math
    import pandas as pd
    rng = np.random.default_rng(7)
    base = rng.normal(0, 0.01, 400)
    # A0 正常; A1 = A0 完全共线(多重共线性); A2 常数(零方差, 停牌)
    df = pd.DataFrame({
        "A0": base,
        "A1": base,                 # 与 A0 完全相关 -> 协方差奇异
        "A2": 0.0,                  # 零方差 -> 对角 0
    })
    for method in ["all_risk_parity", "all_max_sharpe", "sharpe_sq_risk_budget"]:
        w, _ = optimize(df, method=method, ratio="sharpe")
        assert w.notna().all(), f"{method} 产生 NaN: {w.to_dict()}"
        assert math.isfinite(float(w.sum()))
        assert abs(float(w.sum()) - 1.0) < 1e-6, f"{method} 权重和≠1: {w.sum()}"
        assert (w >= -1e-9).all(), f"{method} 非长仓: {w.to_dict()}"

    # 直接验证 _regularize_cov 把奇异协方差变为正定(最小特征值 > 0)
    from bp_api.quant.optimizer import _regularize_cov
    sing = np.array([[1e-4, 1e-4, 0.0], [1e-4, 1e-4, 0.0], [0.0, 0.0, 0.0]])
    reg = _regularize_cov(sing)
    eigvals = np.linalg.eigvalsh(reg)
    assert (eigvals > 0).all(), f"正则后非正定: {eigvals}"
