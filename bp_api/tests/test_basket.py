"""P4: 一篮子资产风险平价 —— 6 方法优化器 + /api/basket 路由测试。

不连数据库：路由测试直接调用 ``register_routes`` 注册后的 endpoint 函数，
``db.get_conn`` / ``repositories.load_price_panel`` 由 monkeypatch 打桩
（与 ``test_otc_pricing.py`` 的仓库约定一致，不引入 TestClient 依赖）。
"""

from __future__ import annotations

import inspect
import math
from contextlib import contextmanager
from datetime import date

import numpy as np
import pandas as pd
import pytest
from fastapi import FastAPI, HTTPException
from pydantic import ValidationError

from bp_api import auth, basket
from bp_api.quant import basket as qbasket
from bp_api.schemas import BasketBacktestIn, BasketOptimizeIn

EXPECTED_METHODS = (
    "risk_parity",
    "max_sharpe",
    "max_sortino",
    "min_variance",
    "equal_weight",
    "risk_budget",
)


# ---------------------------------------------------------------------------
# 夹具
# ---------------------------------------------------------------------------
def _returns(n: int = 400, seed: int = 7, cols=("A", "B", "C")) -> pd.DataFrame:
    rng = np.random.default_rng(seed)
    data = {
        c: rng.normal(0.0004 * (i + 1), 0.008 + 0.004 * i, n)
        for i, c in enumerate(cols)
    }
    return pd.DataFrame(data)


def _panel(n: int = 420, seed: int = 11) -> pd.DataFrame:
    dates = [d.date() for d in pd.bdate_range("2021-01-04", periods=n)]
    rng = np.random.default_rng(seed)
    return pd.DataFrame(
        {
            "A@s": 100.0 * np.exp(np.cumsum(rng.normal(0.0004, 0.010, n))),
            "B@s": 100.0 * np.exp(np.cumsum(rng.normal(0.0002, 0.008, n))),
            "C@s": 100.0 * np.exp(np.cumsum(rng.normal(0.0003, 0.012, n))),
        },
        index=dates,
    )


def _risk_contributions(w: np.ndarray, cov: np.ndarray) -> np.ndarray:
    vol = float(np.sqrt(max(float(w @ cov @ w), 1e-18)))
    return w * (cov @ w) / vol


@contextmanager
def _fake_conn():
    yield object()


def _patch_quotes(monkeypatch, panel: pd.DataFrame) -> dict:
    """把 DB 连接与行情面板整体打桩；返回 seen 记录供断言。"""
    monkeypatch.setattr(basket.db, "get_conn", _fake_conn)
    seen: dict = {}

    def fake_load(conn, pairs):
        seen["pairs"] = list(pairs)
        return panel.copy()

    monkeypatch.setattr(basket.repo, "load_price_panel", fake_load)
    return seen


@pytest.fixture
def endpoints() -> dict[str, object]:
    app = FastAPI()
    basket.register_routes(app)
    return {getattr(r, "path", None): r.endpoint for r in app.routes}


def _optimize_payload(**overrides) -> BasketOptimizeIn:
    body = {
        "assets": [{"symbol": "A", "source": "s"}, {"symbol": "B", "source": "s"}],
        "method": "risk_parity",
        "lookback_days": 156,
        "risk_free": 0.02,
    }
    body.update(overrides)
    return BasketOptimizeIn.model_validate(body)


# ---------------------------------------------------------------------------
# 1. 方法白名单与权重约束
# ---------------------------------------------------------------------------
def test_methods_constant_is_exact_whitelist():
    assert qbasket.METHODS == EXPECTED_METHODS
    assert len(set(qbasket.METHODS)) == 6


def test_unknown_method_raises_value_error():
    with pytest.raises(ValueError):
        qbasket.optimize(_returns(120).values, "does_not_exist", lookback=60, risk_free=0.0)


@pytest.mark.parametrize("method", EXPECTED_METHODS)
def test_six_methods_return_valid_weights(method):
    df = _returns(300)
    w = qbasket.optimize(df.values, method, lookback=156, risk_free=0.02)

    assert isinstance(w, np.ndarray)
    assert w.shape == (df.shape[1],)
    assert np.isfinite(w).all()
    assert abs(float(w.sum()) - 1.0) < 1e-8
    assert (w >= 0.0).all()


def test_weights_are_long_only_with_mixed_means():
    """含负均值资产时，SLSQP/解析解都不得产出负权重。"""
    rng = np.random.default_rng(3)
    df = pd.DataFrame(
        {
            "up": rng.normal(0.0010, 0.010, 300),
            "down": rng.normal(-0.0010, 0.006, 300),
            "flat": rng.normal(0.0, 0.004, 300),
        }
    )
    for method in EXPECTED_METHODS:
        w = qbasket.optimize(df.values, method, lookback=200, risk_free=0.01)
        assert (w >= 0.0).all(), f"{method} 出现负权重: {w}"
        assert abs(float(w.sum()) - 1.0) < 1e-8


# ---------------------------------------------------------------------------
# 2. 退化情形
# ---------------------------------------------------------------------------
def test_single_asset_returns_full_weight():
    w = qbasket.optimize(_returns(100, cols=("only",)).values, "risk_parity",
                         lookback=60, risk_free=0.0)
    assert np.allclose(w, np.array([1.0]), atol=1e-12)


def test_single_effective_asset_after_nan_filter():
    rng = np.random.default_rng(5)
    arr = np.column_stack([
        rng.normal(0.0005, 0.01, 200),
        np.full(200, np.nan),
    ])
    for method in EXPECTED_METHODS:
        w = qbasket.optimize(arr, method, lookback=120, risk_free=0.0)
        assert np.isfinite(w).all()
        assert w[0] == pytest.approx(1.0, abs=1e-9)
        assert w[1] == pytest.approx(0.0, abs=1e-12)


def test_perfectly_correlated_assets_degenerate_cov():
    base = np.random.default_rng(6).normal(0.0003, 0.01, 250)
    arr = np.column_stack([base, base, base * 0.5])
    for method in EXPECTED_METHODS:
        w = qbasket.optimize(arr, method, lookback=180, risk_free=0.0)
        assert np.isfinite(w).all(), f"{method} 产生 NaN"
        assert (w >= 0.0).all()
        assert abs(float(w.sum()) - 1.0) < 1e-8


def test_all_zero_variance_does_not_throw():
    arr = np.zeros((120, 3))
    for method in EXPECTED_METHODS:
        w = qbasket.optimize(arr, method, lookback=100, risk_free=0.0)
        assert np.isfinite(w).all(), f"{method} 产生 NaN"
        assert abs(float(w.sum()) - 1.0) < 1e-8
        assert (w >= 0.0).all()


def test_empty_and_one_row_inputs_degrade_to_equal_weight():
    empty = np.empty((0, 3))
    w0 = qbasket.optimize(empty, "risk_parity", lookback=60, risk_free=0.0)
    assert np.allclose(w0, np.full(3, 1.0 / 3.0))

    one_row = np.array([[0.01, 0.02, -0.01]])
    w1 = qbasket.optimize(one_row, "max_sharpe", lookback=60, risk_free=0.0)
    assert np.allclose(w1, np.full(3, 1.0 / 3.0))

    no_assets = np.empty((10, 0))
    w2 = qbasket.optimize(no_assets, "risk_parity", lookback=60, risk_free=0.0)
    assert w2.shape == (0,)


# ---------------------------------------------------------------------------
# 3. lookback 与风险预算
# ---------------------------------------------------------------------------
def test_lookback_uses_only_trailing_window():
    full = _returns(300, seed=9).values
    tail = full[-40:]
    w_full = qbasket.optimize(full, "min_variance", lookback=40, risk_free=0.0)
    w_tail = qbasket.optimize(tail, "min_variance", lookback=40, risk_free=0.0)
    assert np.allclose(w_full, w_tail, atol=1e-12)


def test_risk_budget_custom_contributions():
    from bp_api.quant.optimizer import _regularize_cov

    df = _returns(400, seed=13, cols=("A", "B"))
    w = qbasket.optimize(
        df, "risk_budget", lookback=300, risk_free=0.0,
        risk_budget={"A": 0.8, "B": 0.2},
    )
    # 求解器实际使用的是正则化后的协方差（收缩 + ridge），按其验证风险贡献比例。
    cov = _regularize_cov(np.cov(df.values[-300:], rowvar=False, ddof=1))
    rc = _risk_contributions(w, cov)
    assert rc[0] > 0 and rc[1] > 0
    assert rc[0] / rc[1] == pytest.approx(4.0, rel=1e-6)


def test_risk_budget_default_equals_risk_parity():
    df = _returns(300, seed=15)
    w_budget = qbasket.optimize(df, "risk_budget", lookback=200, risk_free=0.0)
    w_rp = qbasket.optimize(df, "risk_parity", lookback=200, risk_free=0.0)
    assert np.allclose(w_budget, w_rp, atol=1e-8)


def test_risk_budget_sum_not_one_raises():
    df = _returns(200, seed=17)
    with pytest.raises(ValueError, match="risk_budget"):
        qbasket.optimize(
            df, "risk_budget", lookback=150, risk_free=0.0,
            risk_budget={"A": 0.6, "B": 0.2, "C": 0.1},
        )


def test_risk_budget_negative_raises():
    df = _returns(200, seed=19)
    with pytest.raises(ValueError, match="risk_budget"):
        qbasket.optimize(
            df, "risk_budget", lookback=150, risk_free=0.0,
            risk_budget={"A": 1.2, "B": -0.2, "C": 0.0},
        )


# ---------------------------------------------------------------------------
# 4. 方法经济含义（粗粒度）
# ---------------------------------------------------------------------------
def test_min_variance_vol_not_above_equal_weight():
    df = _returns(300, seed=21, cols=("low_vol", "high_vol"))
    df["high_vol"] = df["high_vol"] * 4.0
    cov = np.cov(df.values[-200:], rowvar=False, ddof=1)
    w_mv = qbasket.optimize(df.values, "min_variance", lookback=200, risk_free=0.0)
    w_eq = np.array([0.5, 0.5])
    vol_mv = math.sqrt(float(w_mv @ cov @ w_mv))
    vol_eq = math.sqrt(float(w_eq @ cov @ w_eq))
    assert vol_mv <= vol_eq + 1e-12


def test_max_sharpe_not_worse_than_equal_weight_in_sample():
    rng = np.random.default_rng(23)
    df = pd.DataFrame(
        {
            "good": rng.normal(0.0015, 0.008, 300),
            "bad": rng.normal(-0.0005, 0.020, 300),
        }
    )
    rf_daily = 0.0
    w = qbasket.optimize(df.values, "max_sharpe", lookback=250, risk_free=rf_daily)
    r = df.values[-250:]
    mean = r.mean(axis=0)
    cov = np.cov(r, rowvar=False, ddof=1)

    def sharpe(weights):
        vol = math.sqrt(float(weights @ cov @ weights))
        return float(weights @ mean) / vol if vol > 0 else -np.inf

    assert sharpe(w) >= sharpe(np.array([0.5, 0.5])) - 1e-8


def test_max_sortino_runs_and_is_valid():
    df = _returns(300, seed=25)
    w = qbasket.optimize(df.values, "max_sortino", lookback=200, risk_free=0.01)
    assert np.isfinite(w).all()
    assert abs(float(w.sum()) - 1.0) < 1e-8
    assert (w >= 0.0).all()


# ---------------------------------------------------------------------------
# 5. 篮子回测引擎：再平衡语义、无未来函数、日汇总统计
# ---------------------------------------------------------------------------
def _bt(prices: pd.DataFrame, **overrides):
    kw = dict(
        method="risk_parity",
        lookback=60,
        min_window=30,
        rebalance_band=0.05,
        risk_free=0.0,
        trading_days=244,
    )
    kw.update(overrides)
    return qbasket.run_basket_backtest(prices, **kw)


def test_backtest_daily_nav_statistics_are_consistent():
    prices = _panel()
    res = _bt(prices)

    nav = res.nav["nav"]
    ret = res.nav["ret"]
    assert (nav > 0).all()
    assert nav.iloc[0] == pytest.approx(1.0)
    # 日汇总：nav_t = nav_{t-1} * (1 + ret_t)
    implied = nav.shift(1) * (1.0 + ret)
    assert np.allclose(nav.iloc[1:].values, implied.iloc[1:].values, atol=1e-12)
    # 指标口径：年化波动 = 日收益样本标准差 × sqrt(244)
    expected_vol = float(ret.iloc[1:].std(ddof=1) * math.sqrt(244))
    assert res.metrics["annualized_vol"] == pytest.approx(expected_vol, rel=1e-9)
    # 最大回撤与净值序列直接计算一致
    dd = nav / nav.cummax() - 1.0
    assert res.metrics["max_drawdown"] == pytest.approx(float(dd.min()), abs=1e-12)


def test_backtest_no_lookahead():
    prices = _panel(seed=31)
    cutoff = prices.index[len(prices) * 2 // 3]

    res1 = _bt(prices)

    prices2 = prices.copy()
    rng = np.random.default_rng(99)
    mask = prices2.index > cutoff
    prices2.loc[mask] = prices2.loc[mask] * (
        1.0 + rng.normal(0.0, 0.08, prices2.loc[mask].shape)
    )
    res2 = _bt(prices2)

    nav1 = res1.nav["nav"].loc[:cutoff]
    nav2 = res2.nav["nav"].loc[:cutoff]
    common = nav1.index.intersection(nav2.index)
    assert len(common) > 10
    assert np.allclose(nav1.loc[common].values, nav2.loc[common].values, atol=1e-9)


def test_backtest_rebalance_band_semantics():
    prices = _panel(seed=37)
    res_tight = _bt(prices, rebalance_band=0.0)
    res_loose = _bt(prices, rebalance_band=1.0)

    assert len(res_tight.rebalances) > len(res_loose.rebalances)
    assert len(res_loose.rebalances) == 1  # 仅建仓
    for rb in res_tight.rebalances[1:]:
        assert rb["max_deviation"] > 0.0
    for rb in res_tight.rebalances:
        assert abs(sum(rb["target_weights"].values()) - 1.0) < 1e-8


def test_backtest_turnover_and_asset_contributions():
    prices = _panel(seed=41)
    res = _bt(prices, rebalance_band=0.0)

    assert res.total_turnover >= 1.0  # 建仓 0→目标 = 100% 换手
    assert res.annualized_turnover >= 0.0
    assert len(res.rebalances) >= 2

    contribs = res.asset_contributions
    assert {c["key"] for c in contribs} == set(prices.columns)
    # Carino 链接贡献之和 ≈ 组合总收益
    assert abs(sum(c["contribution"] for c in contribs) - res.metrics["total_return"]) < 0.01


def test_backtest_partial_asset_inclusion_does_not_delay_start():
    dates = [d.date() for d in pd.bdate_range("2020-01-01", periods=360)]
    rng = np.random.default_rng(43)
    early = 100.0 * np.exp(np.cumsum(rng.normal(0.0004, 0.010, len(dates))))
    late_start = 120
    late_vals = 100.0 * np.exp(
        np.cumsum(rng.normal(0.0004, 0.010, len(dates) - late_start))
    )
    late = np.full(len(dates), np.nan)
    late[late_start:] = late_vals
    prices = pd.DataFrame({"early@s": early, "late@s": late}, index=dates)

    res = _bt(prices, lookback=40, min_window=20, rebalance_band=0.05)
    assert res.effective_start < dates[late_start]
    assert res.daily_weights["late@s"].iloc[0] == pytest.approx(0.0)
    assert float(res.daily_weights["late@s"].max()) > 0.0


# ---------------------------------------------------------------------------
# 6. /api/basket 路由
# ---------------------------------------------------------------------------
def test_optimize_endpoint_returns_weights_and_diagnostics(
    endpoints, monkeypatch
):
    panel = _panel()
    seen = _patch_quotes(monkeypatch, panel)
    handler = endpoints["/api/basket/optimize"]

    body = handler(_optimize_payload(lookback_days=156), None)

    assert seen["pairs"] == [("A", "s"), ("B", "s")]
    assert body["method"] == "risk_parity"
    assert [w["symbol"] for w in body["weights"]] == ["A", "B"]
    assert abs(sum(w["weight"] for w in body["weights"]) - 1.0) < 1e-8
    diag = body["diagnostics"]
    assert diag["method"] == "risk_parity"
    assert diag["lookback"] == 156
    assert diag["n_obs"] == 156
    assert diag["effective_start"] == str(panel.index[-156])
    assert diag["volatility"] >= 0.0
    assert math.isfinite(diag["sharpe"])


def test_optimize_endpoint_lookback_insufficient_returns_400(
    endpoints, monkeypatch
):
    _patch_quotes(monkeypatch, _panel(n=120))
    handler = endpoints["/api/basket/optimize"]

    with pytest.raises(HTTPException) as exc:
        handler(_optimize_payload(lookback_days=500), None)
    assert exc.value.status_code == 400
    assert "回看" in str(exc.value.detail) or "lookback" in str(exc.value.detail)


def test_optimize_endpoint_unknown_method_returns_400(endpoints, monkeypatch):
    _patch_quotes(monkeypatch, _panel())
    handler = endpoints["/api/basket/optimize"]
    with pytest.raises(HTTPException) as exc:
        handler(_optimize_payload(method="bogus"), None)
    assert exc.value.status_code == 400
    assert "method" in str(exc.value.detail).lower()


def test_optimize_endpoint_invalid_risk_budget_returns_400(endpoints, monkeypatch):
    _patch_quotes(monkeypatch, _panel())
    handler = endpoints["/api/basket/optimize"]

    with pytest.raises(HTTPException) as exc:
        handler(
            _optimize_payload(
                method="risk_budget",
                risk_budget={"A@s": 0.6, "B@s": 0.2},
            ),
            None,
        )
    assert exc.value.status_code == 400
    assert "risk_budget" in str(exc.value.detail)


def test_optimize_endpoint_missing_quote_returns_404(endpoints, monkeypatch):
    monkeypatch.setattr(basket.db, "get_conn", _fake_conn)

    def fail(conn, pairs):
        raise ValueError("A@s 无清洗行情数据, 请先运行 ingest/clean")

    monkeypatch.setattr(basket.repo, "load_price_panel", fail)
    handler = endpoints["/api/basket/optimize"]

    with pytest.raises(HTTPException) as exc:
        handler(_optimize_payload(), None)
    assert exc.value.status_code == 404


def test_backtest_endpoint_returns_curve_and_stats(endpoints, monkeypatch):
    panel = _panel()
    _patch_quotes(monkeypatch, panel)
    handler = endpoints["/api/basket/backtest"]

    payload = BasketBacktestIn.model_validate(
        {
            "assets": [
                {"symbol": "A", "source": "s"},
                {"symbol": "B", "source": "s"},
                {"symbol": "C", "source": "s"},
            ],
            "method": "min_variance",
            "lookback_days": 60,
            "risk_free": 0.0,
            "rebalance_band": 0.05,
        }
    )
    body = handler(payload, None)

    assert body["method"] == "min_variance"
    assert body["effective_start"]
    assert len(body["nav"]) > 10
    assert body["nav"][0]["nav"] == pytest.approx(1.0)
    assert body["nav"][0]["ret"] == pytest.approx(0.0)
    assert math.isfinite(body["annualized_return"])
    assert body["annualized_vol"] >= 0.0
    assert body["max_drawdown"] <= 0.0
    assert body["turnover"] >= 0.0
    assert body["turnover_total"] >= 1.0
    assert {c["symbol"] for c in body["contributions"]} == {"A", "B", "C"}
    assert abs(sum(w["weight"] for w in body["weights"]) - 1.0) < 1e-8
    assert isinstance(body["rebalances"], list)


def test_basket_routes_use_optional_user_dependency(endpoints):
    for path in ("/api/basket/optimize", "/api/basket/backtest"):
        sig = inspect.signature(endpoints[path])
        dep = sig.parameters["user"].default
        assert getattr(dep, "dependency", None) is auth.optional_user


def test_basket_schema_validates_inputs():
    with pytest.raises(ValidationError):
        BasketOptimizeIn.model_validate(
            {"assets": [], "method": "risk_parity", "lookback_days": 60}
        )
    with pytest.raises(ValidationError):
        BasketOptimizeIn.model_validate(
            {
                "assets": [{"symbol": "A", "source": "s"}],
                "method": "risk_parity",
                "lookback_days": 1,
            }
        )
    with pytest.raises(ValidationError):
        BasketBacktestIn.model_validate(
            {
                "assets": [{"symbol": "A", "source": "s"}],
                "method": "risk_parity",
                "lookback_days": 60,
                "start": "2024-01-02",
                "end": "2023-01-02",
            }
        )


def test_optimize_endpoint_end_truncates_and_start_relaxes_window(
    endpoints, monkeypatch
):
    panel = _panel()
    _patch_quotes(monkeypatch, panel)
    handler = endpoints["/api/basket/optimize"]

    end = panel.index[-100]
    body = handler(_optimize_payload(lookback_days=60, end=end), None)
    assert body["diagnostics"]["n_obs"] == 60
    # 60 个收益窗口覆盖价格下标 [end-59, end]；end = -100 → 起点 -159。
    assert body["diagnostics"]["effective_start"] == str(panel.index[-159])

    # 指定 start 后允许窗口短于 lookback_days（用户主动限定区间）。
    start = panel.index[-30]
    body2 = handler(_optimize_payload(lookback_days=60, start=start), None)
    assert body2["diagnostics"]["n_obs"] == 30
    assert body2["diagnostics"]["effective_start"] == str(start)


def test_optimize_endpoint_unknown_risk_budget_asset_returns_400(
    endpoints, monkeypatch
):
    _patch_quotes(monkeypatch, _panel())
    handler = endpoints["/api/basket/optimize"]
    with pytest.raises(HTTPException) as exc:
        handler(
            _optimize_payload(
                method="risk_budget",
                risk_budget={"A@s": 0.5, "MISSING@s": 0.5},
            ),
            None,
        )
    assert exc.value.status_code == 400
    assert "risk_budget" in str(exc.value.detail)


def test_optimize_endpoint_duplicate_assets_returns_400(endpoints, monkeypatch):
    _patch_quotes(monkeypatch, _panel())
    handler = endpoints["/api/basket/optimize"]
    payload = BasketOptimizeIn.model_validate(
        {
            "assets": [
                {"symbol": "A", "source": "s"},
                {"symbol": "A", "source": "s"},
            ],
            "method": "risk_parity",
            "lookback_days": 60,
        }
    )
    with pytest.raises(HTTPException) as exc:
        handler(payload, None)
    assert exc.value.status_code == 400
    assert "重复" in str(exc.value.detail)
