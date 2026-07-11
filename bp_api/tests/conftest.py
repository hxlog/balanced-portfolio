"""测试公共夹具: 合成行情数据。"""

from __future__ import annotations

import os

import numpy as np
import pandas as pd
import pytest


os.environ["BP_JWT_SECRET"] = "balanced-portfolio-test-jwt-secret"


@pytest.fixture
def rng():
    return np.random.default_rng(42)


def _gbm(rng, n, mu, sigma, s0=100.0):
    rets = rng.normal(mu, sigma, n)
    return s0 * np.exp(np.cumsum(rets))


@pytest.fixture
def synthetic_returns(rng):
    """5 资产 500 日的日收益矩阵。"""
    dates = pd.bdate_range("2022-01-01", periods=500)
    data = {
        f"A{i}": rng.normal(0.0003 * (i + 1), 0.01 + 0.002 * i, len(dates))
        for i in range(5)
    }
    return pd.DataFrame(data, index=[d.date() for d in dates])


@pytest.fixture
def synthetic_prices(rng):
    """6 资产 + 基准的价格面板(A股工作日近似)。"""
    dates = [d.date() for d in pd.bdate_range("2021-01-01", periods=800)]
    cols = ["A0@s", "A1@s", "A2@s", "A3@s", "A4@s", "A5@s"]
    prices = pd.DataFrame(
        {c: _gbm(rng, len(dates), 0.0004, 0.012 + 0.001 * i) for i, c in enumerate(cols)},
        index=dates,
    )
    bench = pd.Series(_gbm(rng, len(dates), 0.0002, 0.014), index=dates, name="000300@cn_index_em")
    quadrant_assets = {
        "overheat": ["A0@s", "A1@s"],
        "stagflation": ["A2@s"],
        "recovery": ["A3@s"],
        "recession": ["A4@s", "A5@s"],
    }
    return prices, bench, quadrant_assets
