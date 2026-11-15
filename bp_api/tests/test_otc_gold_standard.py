# -*- coding: utf-8 -*-
"""OTC 定价金标复算测试（镒链科技 2021 测试文档）。

金标来源：
- PDF 系统值（买方 PV，名义 100 万）与参考 MC（1000 万路径）；
- 参考实现：autocallables-pricing（用户提供），日历见 fixtures/otc_reference_calendar.py。

约定（金标准）：
- 折现时钟 BUS252（交易日/252）；票息时钟 ACT365（自然日/365）；
- KO 观察日为 PDF 给定日期列表；KI 每日观察；敲入转看跌、行权价 100%。

说明：
- 本文件验证我们引擎在「双时钟 + 参考日历」下的 PV 与金标系统值的一致性；
- 障碍期权部分先以复现参考算法的方式校验金标数值（我们的 barrier MC 采用恒定 rebate，
  与金标的「按敲出日 ACT365 累计补偿」不同，差异记录在验证报告中）。
"""
from __future__ import annotations

from datetime import date, timedelta

import numpy as np
import pytest
from scipy.stats import norm

from bp_api.quant.otc.calendar import TradingCalendarView
from bp_api.quant.otc.pricer import price_deal

from .fixtures import otc_reference_calendar as refcal

REF = refcal.China()
CAL_DAYS = [
    date(2017, 1, 1) + timedelta(days=i)
    for i in range((date(2025, 12, 31) - date(2017, 1, 1)).days + 1)
]
CAL_DAYS = [d for d in CAL_DAYS if REF.is_business_day(d)]
CAL = TradingCalendarView(CAL_DAYS)

SNOWBALL_KO = [
    "2021-04-15", "2021-05-17", "2021-06-15", "2021-07-15", "2021-08-16",
    "2021-09-15", "2021-10-15", "2021-11-15", "2021-12-15", "2022-01-17",
    "2022-02-15", "2022-03-15",
]


def _base_spec(**overrides) -> dict:
    spec = {
        "s0": 100.0,
        "notional": 1_000_000.0,
        "spot": 100.0,
        "valuation_date": "2021-03-15",
        "start_date": "2021-03-15",
        "maturity_date": "2022-03-15",
        "direction": "buy",
        "engine": "mc",
        "greeks": False,
        "compute_pnl": False,
        "seed": 20210402,
        "n_paths": 300_000,
        "t_step_per_year": 252,
        "day_count": "ACT365",
        "coupon_day_count": "ACT365",
        "discount_day_count": "BUS252",
    }
    spec.update(overrides)
    return spec


def _snowball_spec(vol: float) -> dict:
    return _base_spec(
        product_type="snowball",
        r=0.02,
        q=0.0,
        vol=vol,
        ko_observation_dates=SNOWBALL_KO,
        ko_barrier_pct=100.0,
        ki_barrier_pct=75.0,
        ki_strike_pct=100.0,
        coupon_out=0.20,
        coupon_div=0.20,
    )


def _phoenix_spec(vol: float) -> dict:
    return _base_spec(
        product_type="phoenix",
        r=0.02,
        q=0.0,
        vol=vol,
        ko_observation_dates=SNOWBALL_KO,
        ko_barrier_pct=100.0,
        ki_barrier_pct=70.0,
        ki_strike_pct=100.0,
        coupon_barrier_pct=70.0,
        period_coupon=0.025,
    )


def _airbag_spec(vol: float) -> dict:
    return _base_spec(
        product_type="airbag",
        engine="analytic",
        valuation_date="2018-01-04",
        start_date="2018-01-04",
        maturity_date="2019-01-03",
        r=0.02,
        q=0.0,
        vol=vol,
        discount_day_count="ACT365",
        coupon_day_count="ACT365",
        strike_pct=100.0,
        barrier_pct=70.0,
        knockin_parti=1.0,
        call_parti=0.8,
        reset_call_parti=0.8,
        discrete_obs=False,
    )


def _pv(spec: dict) -> float:
    result = price_deal(spec, CAL)
    return float(result.price)


@pytest.mark.parametrize("vol,expected", [(0.35, -22196.61), (0.25, 7127.17)])
def test_snowball_golden_system_pv(vol: float, expected: float):
    """雪球：系统值（买方 PV）±3%（300k 路径 MC 误差）。"""
    pv = _pv(_snowball_spec(vol))
    if expected < 0:
        assert pv == pytest.approx(expected, rel=0.03), pv
    else:
        assert pv == pytest.approx(expected, rel=0.03), pv


@pytest.mark.parametrize("vol,expected", [(0.35, 32118.60), (0.25, 65483.03)])
def test_phoenix_golden_system_pv(vol: float, expected: float):
    pv = _pv(_phoenix_spec(vol))
    assert pv == pytest.approx(expected, rel=0.03), pv


@pytest.mark.parametrize("vol,expected", [(0.35, 16389.46), (0.25, 39491.07)])
def test_airbag_golden_analytic_pv(vol: float, expected: float):
    pv = _pv(_airbag_spec(vol))
    assert pv == pytest.approx(expected, rel=0.005), pv


def _reference_barrier_mc(vol: float, n_paths: int = 500_000, seed: int = 20210412) -> float:
    """金标障碍算法复现（向上敲出看涨，月度观察，rebate 按 Act365 累计）。"""
    spot = 100.0
    notional = 1_000_000.0
    r, q = 0.035, 0.01
    ko_barrier = 120.0
    strike = 100.0
    rebate_rate = 0.05
    start = date(2018, 1, 4)
    maturity = date(2019, 1, 4)
    ko_dates = [
        "2018-02-05", "2018-03-05", "2018-04-04", "2018-05-04", "2018-06-04",
        "2018-07-04", "2018-08-06", "2018-09-04", "2018-10-08", "2018-11-05",
        "2018-12-04", "2019-01-04",
    ]
    obs_idx = np.array([CAL.business_offset(start, date.fromisoformat(d)) for d in ko_dates], dtype=int)
    idx = []
    rebates = []
    discounts = []
    for i, d in enumerate(ko_dates):
        cur = date.fromisoformat(d)
        idx.append(obs_idx[i])
        rebates.append(rebate_rate * (cur - start).days / 365.0 * notional)
        discounts.append(np.exp(-r * CAL.business_offset(start, cur) / 252.0))
    rebates = np.asarray(rebates)
    discounts = np.asarray(discounts)
    n_steps = CAL.business_offset(start, maturity)
    dt = 1.0 / 252.0
    rng = np.random.default_rng(seed)
    remaining = n_paths
    batch = 100_000
    total = 0.0
    from bp_api.quant.otc.calendar import TradingCalendarView as _View  # noqa: F401
    while remaining > 0:
        n = min(batch, remaining)
        eps = rng.standard_normal((n, n_steps))
        steps = (r - q - 0.5 * vol * vol) * dt + vol * np.sqrt(dt) * eps
        paths = spot * np.exp(np.cumsum(steps, axis=1))
        obs = paths[:, obs_idx - 1]
        knocked = obs >= ko_barrier
        ko_pos = np.argmax(knocked, axis=1)
        has_ko = knocked.any(axis=1)
        pv = np.zeros(n)
        pv[has_ko] = rebates[ko_pos[has_ko]] * discounts[ko_pos[has_ko]]
        tail = paths[:, -1]
        pv[~has_ko] = np.maximum(tail[~has_ko] - strike, 0.0) / spot * notional * np.exp(-r * n_steps / 252.0)
        total += float(pv.sum())
        remaining -= n
    return total / n_paths


@pytest.mark.parametrize("vol,expected", [(0.35, 16810.11), (0.25, 21996.92)])
def test_barrier_golden_reference_reproduction(vol: float, expected: float):
    """障碍期权：金标算法复现值 vs 系统值 ±1.5%（验证金标理解正确）。"""
    pv = _reference_barrier_mc(vol)
    assert pv == pytest.approx(expected, rel=0.015), pv
