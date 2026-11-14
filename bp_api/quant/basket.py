"""一篮子资产风险平价（6 方法）。

与 `quant/optimizer.py` 的四象限方法不同，这里不划分象限，直接在给定资产池上
求一组长仓权重。方法名采用前端篮子模式的短标识：

  risk_parity    等风险贡献（ERC，复用 optimizer.risk_parity_weights / Spinu CCD）
  max_sharpe     最大夏普（SLSQP + 逆波动率热启动，复用 optimizer.max_ratio_weights）
  max_sortino    最大索提诺（同上）
  min_variance   最小方差（解析解 + 轻微 ridge；负权重截断后归一）
  equal_weight   等权
  risk_budget    自定义风险预算（复用 optimizer.risk_budget_ccd；默认等风险贡献）

退化处理（不抛未捕获异常）：
  - 单资产 / 仅一个有效资产 → 100% 该资产；
  - 窗口为空、只有 1 行、全部资产无有效值 → 等权兜底；
  - 奇异/零方差协方差 → optimizer._regularize_cov（收缩 + ridge）后再求解；
  - 求解结果含 NaN/Inf → 清洗、截断负值并重新归一。

回测引擎 `run_basket_backtest` 复用 `quant/backtest.py` 的再平衡语义：
  - 任一资产漂移权重偏离当日最优目标 > rebalance_band（绝对值）→ 整体回到目标；
  - 当日 NAV 用当日收益更新，次日才使用新权重（无未来函数）；
  - 不足窗口的资产权重为 0，不拖后整体 effective_start。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, datetime
from typing import Optional

import numpy as np
import pandas as pd

from .backtest import _union_calendar
from .coverage import available_at, effective_min_window, window_bounds
from .metrics import compute_metrics
from .optimizer import (
    _regularize_cov,
    _regularize_mean,
    max_ratio_weights,
    risk_budget_ccd,
    risk_parity_weights,
)

METHODS = (
    "risk_parity",
    "max_sharpe",
    "max_sortino",
    "min_variance",
    "equal_weight",
    "risk_budget",
)

DEFAULT_TRADING_DAYS = 244
_BUDGET_TOL = 1e-6
_MIN_RIDGE = 1e-12

METHOD_LABELS_CN = {
    "risk_parity": "风险平价",
    "max_sharpe": "最大夏普",
    "max_sortino": "最大 Sortino",
    "min_variance": "最小方差",
    "equal_weight": "等权",
    "risk_budget": "风险预算",
}


# ---------------------------------------------------------------------------
# 输入标准化 / 小工具
# ---------------------------------------------------------------------------
def _as_matrix(returns) -> tuple[np.ndarray, Optional[list[str]]]:
    """把 ndarray / DataFrame 统一成 (T, n) 的 float 矩阵并保留列名。"""
    if isinstance(returns, pd.DataFrame):
        labels = [str(c) for c in returns.columns]
        arr = returns.to_numpy(dtype=float)
    else:
        labels = None
        arr = np.asarray(returns, dtype=float)

    if arr.ndim == 0:
        arr = arr.reshape(1, 1)
    elif arr.ndim == 1:
        # 空的一维输入视为「没有资产」；非空一维视为单资产收益序列。
        arr = arr.reshape(0, 0) if arr.size == 0 else arr.reshape(-1, 1)
    elif arr.ndim != 2:
        raise ValueError("returns 必须是二维矩阵 (T, n)")
    return arr, labels


def _equal_weights(n: int) -> np.ndarray:
    if n <= 0:
        return np.zeros(0, dtype=float)
    return np.full(n, 1.0 / n, dtype=float)


def _resolve_lookback(lookback, n_rows: int) -> int:
    """返回实际使用的窗口长度；lookback<=0/None 时使用全部历史。"""
    try:
        lb = int(lookback)
    except (TypeError, ValueError):
        lb = n_rows
    if lb <= 0:
        return n_rows
    return min(lb, n_rows)


def _usable_mask(window: np.ndarray) -> np.ndarray:
    """窗口内至少 2 个有限收益的资产才参与优化（单行窗口放宽为 1 个）。"""
    finite = np.isfinite(window)
    counts = finite.sum(axis=0)
    need = 2 if window.shape[0] >= 2 else 1
    return counts >= need


def _clean_weights(w: np.ndarray, n: int) -> np.ndarray:
    """长仓归一化；NaN/Inf 归 0，失败时回退等权。"""
    arr = np.asarray(w, dtype=float).reshape(-1)
    if arr.size != n:
        return _equal_weights(n)
    arr = np.nan_to_num(arr, nan=0.0, posinf=0.0, neginf=0.0)
    arr = np.clip(arr, 0.0, None)
    total = float(arr.sum())
    if not np.isfinite(total) or total <= _MIN_RIDGE:
        return _equal_weights(n)
    return arr / total


def _inverse_vol_weights(cov: np.ndarray) -> np.ndarray:
    diag = np.clip(np.diag(cov), _MIN_RIDGE, None)
    inv = 1.0 / np.sqrt(diag)
    return inv / inv.sum()


def _min_variance_weights(cov: np.ndarray) -> np.ndarray:
    """解析最小方差 w ∝ Σ⁻¹1，负权重截断后归一（长仓近似解）。"""
    n = cov.shape[0]
    if n == 1:
        return np.array([1.0])
    one = np.ones(n)
    try:
        inv = np.linalg.inv(cov)
    except np.linalg.LinAlgError:
        inv = np.linalg.pinv(cov)
    w = np.asarray(inv @ one, dtype=float)
    denom = float(one @ w)
    if not np.isfinite(denom) or abs(denom) <= _MIN_RIDGE:
        return _inverse_vol_weights(cov)
    w = w / denom
    if not np.isfinite(w).all():
        return _inverse_vol_weights(cov)
    w = np.clip(w, 0.0, None)
    total = float(w.sum())
    if total <= _MIN_RIDGE:
        return _inverse_vol_weights(cov)
    return w / total


def _budget_vector(
    risk_budget: Optional[dict[str, float]],
    labels: Optional[list[str]],
    usable: np.ndarray,
    n: int,
) -> np.ndarray:
    """把 risk_budget 映射到 **有效资产子集** 上并归一。

    - DataFrame 输入优先按列名匹配；
    - ndarray 输入支持 "0"/"1" 之类的下标键，或按插入顺序（长度必须为 n）；
    - 缺失键视为 0 预算；非法/负值/合计≠1 抛 ValueError（路由层转 400）。
    """
    k = int(usable.sum())
    if risk_budget is None:
        return np.ones(k, dtype=float)

    if not isinstance(risk_budget, dict) or not risk_budget:
        raise ValueError("risk_budget 不能为空")

    values = np.asarray(list(risk_budget.values()), dtype=float)
    if not np.isfinite(values).all():
        raise ValueError("risk_budget 含 NaN/Inf")
    if (values < 0).any():
        raise ValueError("risk_budget 不能为负")

    keys = list(risk_budget.keys())
    full = np.zeros(n, dtype=float)

    if labels is not None and all(kk in labels for kk in keys):
        for kk, vv in risk_budget.items():
            full[labels.index(kk)] = float(vv)
    elif all(str(kk).lstrip("-").isdigit() for kk in keys) and all(
        0 <= int(kk) < n for kk in keys
    ):
        for kk, vv in risk_budget.items():
            full[int(kk)] = float(vv)
    elif len(keys) == n:
        full = values.copy()
    else:
        raise ValueError("risk_budget 的键无法对应当前资产（请使用 symbol@source）")

    total = float(full.sum())
    if abs(total - 1.0) > _BUDGET_TOL:
        raise ValueError(f"risk_budget 合计必须为 1（当前 {total:.6f}）")

    sub = full[usable]
    sub_total = float(sub.sum())
    if sub_total <= _MIN_RIDGE:
        raise ValueError("risk_budget 未覆盖任何有效资产")
    return sub / sub_total


# ---------------------------------------------------------------------------
# 顶层优化入口
# ---------------------------------------------------------------------------
def optimize(
    returns: np.ndarray,
    method: str,
    *,
    lookback: int,
    risk_free: float,
    risk_budget: Optional[dict[str, float]] = None,
    trading_days: int = DEFAULT_TRADING_DAYS,
) -> np.ndarray:
    """返回长仓权重（Σ=1），只使用传入窗口的最后 ``lookback`` 行。

    ``returns`` 推荐传 (T, n) ndarray；也接受 DataFrame（risk_budget 可按列名匹配）。
    """
    if method not in METHODS:
        raise ValueError(f"未知优化方法: {method}（可选: {', '.join(METHODS)}）")

    arr, labels = _as_matrix(returns)
    n = int(arr.shape[1])
    if n == 0:
        return np.zeros(0, dtype=float)
    if arr.shape[0] == 0:
        return _equal_weights(n)

    lb = _resolve_lookback(lookback, arr.shape[0])
    window = arr[-lb:] if lb > 0 else arr
    if window.shape[0] == 0:
        return _equal_weights(n)
    if window.shape[0] < 2:
        # 只有 1 个观测，无法估计协方差/均值：有效资产等权兜底。
        usable_one = _usable_mask(window)
        if int(usable_one.sum()) == 0:
            return _equal_weights(n)
        out = np.zeros(n, dtype=float)
        out[usable_one] = 1.0 / int(usable_one.sum())
        return out

    usable = _usable_mask(window)
    k = int(usable.sum())
    if k == 0:
        return _equal_weights(n)
    if k == 1:
        out = np.zeros(n, dtype=float)
        out[int(np.flatnonzero(usable)[0])] = 1.0
        return out

    sub = window[:, usable]
    # 停牌/未上市日按 0 收益处理（与回测引擎的 NaN→0 口径一致）。
    sub = np.nan_to_num(sub, nan=0.0, posinf=0.0, neginf=0.0)

    try:
        cov = np.cov(sub, rowvar=False, ddof=1)
    except Exception:  # noqa: BLE001 - 极端输入下 np.cov 也可能报错
        cov = np.eye(k) * _MIN_RIDGE
    cov = np.asarray(cov, dtype=float)
    if cov.ndim == 0:
        cov = np.array([[float(cov)]])
    cov = _regularize_cov(np.nan_to_num(cov, nan=0.0, posinf=0.0, neginf=0.0))

    mean = np.nan_to_num(sub.mean(axis=0), nan=0.0, posinf=0.0, neginf=0.0)
    try:
        days_per_year = max(int(trading_days), 1)
    except (TypeError, ValueError):
        days_per_year = DEFAULT_TRADING_DAYS
    rf_daily = float(risk_free or 0.0) / days_per_year

    if method == "equal_weight":
        w_sub = np.ones(k, dtype=float) / k

    elif method == "risk_parity":
        w_sub = risk_parity_weights(cov)

    elif method == "risk_budget":
        budgets = _budget_vector(risk_budget, labels, usable, n)
        w_sub = risk_budget_ccd(cov, budgets)

    elif method == "min_variance":
        w_sub = _min_variance_weights(cov)

    else:  # max_sharpe / max_sortino
        ratio = "sharpe" if method == "max_sharpe" else "sortino"
        sub_labels = (
            [label for label, keep in zip(labels, usable) if keep]
            if labels is not None
            else [str(i) for i in range(k)]
        )
        sub_df = pd.DataFrame(sub, columns=sub_labels)
        mean_v = _regularize_mean(mean, rf_daily=rf_daily)
        warm = _inverse_vol_weights(cov)
        w_sub = max_ratio_weights(
            sub_df, ratio, rf_daily, cov=cov, mean=mean_v, x0=warm
        )

    w_sub = _clean_weights(w_sub, k)

    out = np.zeros(n, dtype=float)
    out[usable] = w_sub
    return _clean_weights(out, n)


# ---------------------------------------------------------------------------
# 诊断指标
# ---------------------------------------------------------------------------
def summarize_returns(
    returns,
    weights: np.ndarray,
    *,
    risk_free: float = 0.0,
    trading_days: int = DEFAULT_TRADING_DAYS,
) -> dict:
    """把窗口收益 × 权重合成为日收益，并复用 metrics.compute_metrics 出年化口径。"""
    arr, _ = _as_matrix(returns)
    w = np.asarray(weights, dtype=float).reshape(-1)
    if arr.shape[0] == 0 or arr.shape[1] == 0 or w.size != arr.shape[1]:
        return {
            "n_obs": int(arr.shape[0]),
            "annualized_return": 0.0,
            "annualized_vol": 0.0,
            "sharpe": 0.0,
            "max_drawdown": 0.0,
        }

    clean = np.nan_to_num(arr, nan=0.0, posinf=0.0, neginf=0.0)
    port = clean @ w
    # compute_metrics 的 ytd/年度表需要 date 型索引(与回测引擎一致)；诊断只关心口径。
    index = [
        d.date()
        for d in pd.date_range("2000-01-03", periods=arr.shape[0] + 1, freq="B")
    ]
    # 前面补 1.0，让 compute_metrics 看到窗口内全部日收益。
    nav = pd.Series(
        np.concatenate([[1.0], np.cumprod(1.0 + port)]), index=index
    )
    metrics = compute_metrics(nav, None, risk_free, trading_days)
    return {
        "n_obs": int(arr.shape[0]),
        "annualized_return": float(metrics["annualized_return"]),
        "annualized_vol": float(metrics["annualized_vol"]),
        "sharpe": float(metrics["sharpe"]),
        "max_drawdown": float(metrics["max_drawdown"]),
    }


# ---------------------------------------------------------------------------
# 篮子回测引擎（复用 backtest.py 的再平衡语义）
# ---------------------------------------------------------------------------
@dataclass
class BasketBacktestResult:
    nav: pd.DataFrame                      # index=date, columns: nav, ret
    rebalances: list[dict]
    effective_start: date
    latest_target: dict[str, float]
    daily_weights: pd.DataFrame
    asset_contributions: list[dict]
    total_turnover: float
    annualized_turnover: float
    metrics: dict
    n_obs: int
    latest_drift: dict = field(default_factory=dict)
    end_optimal_target: dict = field(default_factory=dict)


def _safe_numeric_dict(d: dict, ndigits: int = 10) -> dict[str, float]:
    """数值字典清洗（NaN/Inf 归 0），不做归一化 —— 用于 delta。"""
    out: dict[str, float] = {}
    for k, v in d.items():
        try:
            fv = float(v)
        except (TypeError, ValueError):
            fv = 0.0
        out[str(k)] = 0.0 if not np.isfinite(fv) else round(fv, ndigits)
    return out


def _safe_dict(d: dict, ndigits: int = 10) -> dict[str, float]:
    """权重字典清洗 + 保持合计≈1（NaN/Inf 归 0，最大项吸收舍入残差）。"""
    out = _safe_numeric_dict(d, ndigits)
    if out:
        total = sum(out.values())
        if abs(total - 1.0) > 1e-12:
            kmax = max(out, key=lambda k: abs(out[k]))
            out[kmax] += 1.0 - total
    return out


def _budget_subset(
    risk_budget: Optional[dict[str, float]], available: list[str]
) -> Optional[dict[str, float]]:
    """把全资产预算切到当前可用资产并归一；无可用预算时返回 None（等预算兜底）。"""
    if risk_budget is None:
        return None
    sub = {k: float(risk_budget.get(k, 0.0)) for k in available}
    total = sum(sub.values())
    if total <= _MIN_RIDGE:
        return None
    return {k: v / total for k, v in sub.items()}


def run_basket_backtest(
    prices: pd.DataFrame,
    *,
    method: str,
    lookback: int,
    min_window: int = 60,
    rebalance_band: float = 0.05,
    risk_free: float = 0.0,
    risk_budget: Optional[dict[str, float]] = None,
    trading_days: int = DEFAULT_TRADING_DAYS,
    user_start: Optional[date] = None,
) -> BasketBacktestResult:
    """篮子模式逐日回测（无未来函数）。

    prices: index=交易日, columns=资产 key（`symbol@source`），NaN=非真实收盘日。
    再平衡语义与 `quant/backtest.py` 一致：任一资产漂移 > band → 整体回目标。
    """
    if method not in METHODS:
        raise ValueError(f"未知优化方法: {method}")
    if isinstance(user_start, datetime):
        user_start = user_start.date()

    assets = list(prices.columns)
    if not assets:
        raise ValueError("无成分资产")

    try:
        lookback = int(lookback)
    except (TypeError, ValueError):
        lookback = 60
    lookback = max(2, lookback)
    try:
        min_window = int(min_window)
    except (TypeError, ValueError):
        min_window = 60
    min_window = effective_min_window(min_window, lookback)
    try:
        band = max(0.0, float(rebalance_band))
    except (TypeError, ValueError):
        band = 0.05

    price_dates = _union_calendar(prices)
    if len(price_dates) < min_window + 2:
        raise ValueError(
            f"可用历史不足（仅 {len(price_dates)} 个交易日，需 > {min_window + 1}）"
        )

    prices_aligned = prices.reindex(price_dates)
    # ffill(左锚)：内部缺口日收益=0、复牌日收益=真实缺口收益，不引入右锚未来数据。
    returns_df = prices_aligned.ffill().pct_change()
    real_mask = ~np.isnan(prices_aligned.values)
    cum_valid = np.cumsum(real_mask.astype(np.int64), axis=0)

    def available_assets(end_idx: int) -> list[str]:
        return available_at(assets, cum_valid, end_idx, lookback, min_window)

    def opt(end_idx: int) -> pd.Series:
        avail = available_assets(end_idx)
        if not avail:
            return pd.Series(0.0, index=assets)
        a, b = window_bounds(end_idx, lookback)
        sub = returns_df.iloc[a : b + 1][avail]
        budgets = (
            _budget_subset(risk_budget, avail) if method == "risk_budget" else None
        )
        w_sub = optimize(
            sub,
            method,
            lookback=len(sub),
            risk_free=risk_free,
            risk_budget=budgets,
            trading_days=trading_days,
        )
        w = pd.Series(0.0, index=assets)
        for key, value in zip(avail, w_sub):
            w[key] = float(value)
        total = float(w.sum())
        if total > 0:
            w = w / total
        return w

    k_user = (
        next((k for k, d in enumerate(price_dates) if d >= user_start), len(price_dates))
        if user_start is not None
        else 0
    )
    start_k = max(min_window + 1, k_user)

    k0 = None
    for k in range(start_k, len(price_dates)):
        if available_assets(k - 1):
            k0 = k
            break
    if k0 is None:
        raise ValueError("数据不足以从指定开始日回测")

    effective_start = price_dates[k0]

    target = opt(k0 - 1)
    w_actual = target.copy()
    last_target = target

    total_turnover = 1.0  # 建仓 0 → target
    rebalances: list[dict] = [
        {
            "trade_date": effective_start,
            "reason": "建仓",
            "target_weights": _safe_dict(target.to_dict()),
            "prev_weights": None,
            "delta": None,
            "max_deviation": 0.0,
            "turnover": 1.0,
        }
    ]

    rows: list[dict] = [
        {"trade_date": effective_start, "nav": 1.0, "ret": 0.0}
    ]
    weight_rows: list[dict] = [
        {"trade_date": effective_start, **target.to_dict()}
    ]
    nav = 1.0

    for k in range(k0 + 1, len(price_dates)):
        day = price_dates[k]
        r_t = (
            returns_df.iloc[k]
            .reindex(assets)
            .replace([np.inf, -np.inf], 0.0)
            .fillna(0.0)
        )

        weight_rows.append({"trade_date": day, **w_actual.to_dict()})
        port_ret = float((w_actual * r_t).sum())
        nav *= 1.0 + port_ret

        grown = w_actual * (1.0 + r_t)
        total = float(grown.sum())
        w_actual = grown / total if total > 0 else w_actual

        target = opt(k)
        dev_s = (w_actual - target).abs()
        dev = float(dev_s.max())

        if dev > band:
            prev = w_actual.copy()
            delta = target - prev
            turnover = float(delta.abs().sum())
            total_turnover += turnover
            trigger = dev_s.idxmax()
            rebalances.append(
                {
                    "trade_date": day,
                    "reason": (
                        f"再平衡：{trigger} 实际权重 {float(prev[trigger]) * 100:.2f}% "
                        f"偏离目标 {float(target[trigger]) * 100:.2f}%"
                        f"（{dev * 100:.2f}pp > {band * 100:.0f}pp）"
                    ),
                    "target_weights": _safe_dict(target.to_dict()),
                    "prev_weights": _safe_dict(prev.to_dict()),
                    "delta": _safe_numeric_dict(delta.to_dict(), ndigits=10),
                    "max_deviation": dev,
                    "turnover": turnover,
                }
            )
            w_actual = target.copy()
            last_target = target

        rows.append({"trade_date": day, "nav": float(nav), "ret": float(port_ret)})

    nav_df = pd.DataFrame(rows).set_index("trade_date")[["nav", "ret"]]
    daily_weights = (
        pd.DataFrame(weight_rows)
        .set_index("trade_date")
        .reindex(columns=assets)
        .fillna(0.0)
    )

    nav_series = nav_df["nav"]
    metrics = compute_metrics(nav_series, None, risk_free, trading_days)

    # 逐资产贡献（Carino 链接，复用既有归因实现；无基准，β/系统性桶置 0）。
    try:
        from .attribution import compute_attribution

        attribution = compute_attribution(
            daily_weights,
            returns_df,
            None,
            nav_series,
            [{"trade_date": rb["trade_date"], "reason": rb["reason"]} for rb in rebalances],
        )
        contributions = attribution.get("assets", [])
    except Exception:  # noqa: BLE001 - 归因失败不应让回测整体失败
        contributions = []

    n_days = max(0, len(rows) - 1)
    annualized_turnover = (
        total_turnover * trading_days / n_days if n_days > 0 else 0.0
    )

    end_target = opt(len(price_dates) - 1)

    return BasketBacktestResult(
        nav=nav_df,
        rebalances=rebalances,
        effective_start=effective_start,
        latest_target=_safe_dict(last_target.to_dict()),
        daily_weights=daily_weights,
        asset_contributions=contributions,
        total_turnover=float(total_turnover),
        annualized_turnover=float(annualized_turnover),
        metrics=metrics,
        n_obs=n_days,
        latest_drift=_safe_dict(w_actual.to_dict()),
        end_optimal_target=_safe_dict(end_target.to_dict()),
    )
