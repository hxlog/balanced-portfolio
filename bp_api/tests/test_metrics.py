"""绩效指标单测。"""

from __future__ import annotations

from datetime import date

import numpy as np
import pandas as pd

from bp_api.quant.metrics import (
    annual_returns,
    annual_vols,
    compute_metrics,
    max_drawdown,
    max_drawdown_recovery_days,
)


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


# ---------------------------------------------------------------------------
# 年度收益/波动率(需求: /dashboard「区间收益率与波动率」下方新增按年切分的表)
# ---------------------------------------------------------------------------

def _nav_from_yearly(years_returns: dict[int, float], trading_days: int = 244):
    """构造一条净值曲线: 每个自然年先横盘补齐 244 个交易日, 再按给定收益率拉升。

    用「整年 244 点」而非真实交易日, 便于把折算年化后的期望值写成闭式。
    """
    parts = []
    nav = 1.0
    for y in sorted(years_returns):
        dates = pd.bdate_range(f"{y}-01-01", periods=trading_days)
        # 年内前半段不动, 最后一天一次性跳到目标收益 → 年内累计涨幅 == years_returns[y]
        vals = [nav] * (trading_days - 1) + [nav * (1 + years_returns[y])]
        parts.append(pd.Series(vals, index=dates.date))
        nav *= 1 + years_returns[y]
    return pd.concat(parts)


def test_annual_returns_full_years_match_cumulative():
    """完整年份(244 个交易日)折算年化后 == 累计收益, 不引入偏差。"""
    nav = _nav_from_yearly({2023: 0.10, 2024: -0.05})
    m = compute_metrics(nav, None, risk_free=0.0, trading_days=244)
    ar = m["annual_returns"]

    assert set(ar) >= {"2023", "2024", "ytd", "annualized"}
    assert abs(ar["2024"] - (-0.05)) < 1e-9
    # 2023 的基是曲线起点(=1.0), 段内 244 点 → n=244, 折算指数为 1 → 等于累计
    assert abs(ar["2023"] - 0.10) < 1e-9


def test_annual_returns_partial_year_is_annualized_not_cumulative():
    """起始年不足一年: 折算后的值必须 ≠ 年内累计涨幅(否则该列没意义)。"""
    # 半年(122 个交易日)涨 10% → 年化约 (1.1)^(244/122)-1 = 21%
    dates = pd.bdate_range("2024-07-01", periods=122).date
    vals = [1.0] * 121 + [1.10]
    nav = pd.Series(vals, index=dates)
    m = compute_metrics(nav, None, risk_free=0.0, trading_days=244)
    ar = m["annual_returns"]

    assert abs(ar["2024"] - 0.10) > 0.05          # 明显不同于累计的 10%
    assert abs(ar["2024"] - (1.10 ** 2 - 1)) < 1e-9


def test_annual_vols_keys_and_ytd():
    nav = _nav_from_yearly({2023: 0.10, 2024: 0.05})
    m = compute_metrics(nav, None, risk_free=0.0, trading_days=244)
    av = m["annual_vols"]

    assert set(av) >= {"2023", "2024", "ytd", "annualized"}
    # 全区间年化与「区间波动率」表的 annualized 同值(前端两处对齐的前提)
    assert av["annualized"] == m["annualized_vol"]
    assert m["annual_returns"]["annualized"] == m["annualized_return"]
    for k in ("2023", "2024", "ytd"):
        assert av[k] is not None and av[k] >= 0.0


def test_annual_returns_ytd_is_annualized_like_its_year():
    """ytd 与「今年」那一列同段同基同口径(年度表里 ytd 是列的一部分, 不是累计值)。

    注意与 period_returns["ytd"] 区分: 那个是「年初至今」的**累计**涨幅(既有滚动窗口列),
    年度表的 ytd 与相邻年份同尺度, 是折算年化后的值。
    """
    # 2023-12-29 收 1.0 → 2024 年内涨到 1.20(20 个样本点)
    idx = [date(2023, 12, 29)] + list(pd.bdate_range("2024-01-02", periods=20).date)
    nav = pd.Series([1.0] + [1.0 + 0.01 * i for i in range(1, 21)], index=idx)
    m = compute_metrics(nav, None, risk_free=0.0, trading_days=244)

    ar = m["annual_returns"]
    # 基取「年初前最后一个净值」= 1.0 → 累计 20%, 段长 20 → 折算年化 1.2^(244/20)-1
    expected = 1.20 ** (244 / 20) - 1
    assert abs(ar["ytd"] - expected) < 1e-6
    assert ar["ytd"] == ar["2024"]
    # 而 period_returns 的 ytd 仍是累计 20%
    assert abs(m["period_returns"]["ytd"] - 0.20) < 1e-9


def test_annual_vol_keys_align_with_returns_keys():
    """年度表的两行必须列对齐: 键集(除 annualized)完全一致。"""
    nav = _nav_from_yearly({2023: 0.10, 2024: 0.05})
    m = compute_metrics(nav, None, risk_free=0.0, trading_days=244)
    assert set(m["annual_returns"]) == set(m["annual_vols"])


def test_annual_returns_single_point_and_empty_do_not_crash():
    # 直接测两个年度函数(不经过 compute_metrics —— 单点入参会在既有的
    # _downside_vol 上触发 numpy 空切片告警, 与本改动无关)。
    one = pd.Series([1.0], index=[date(2024, 5, 6)])
    assert annual_returns(one, 244) == {"2024": 0.0, "ytd": 0.0}
    assert annual_vols(one, 244) == {"2024": None, "ytd": None}

    empty = pd.Series([], dtype=float)
    assert annual_returns(empty, 244) == {}
    assert annual_vols(empty, 244) == {}
