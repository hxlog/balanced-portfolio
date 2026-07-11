"""无未来函数每日回测引擎(单位净值法)。

输入: 清洗后的价格面板(A股交易日、无内部空值, 列=资产 key)、基准价格序列、象限映射。
规则:
  - 每个交易日用滚动 lookback(默认156)窗口重算最优目标权重(仅用 ≤ 当日数据)。
  - 成分逐步纳入: 尚无足够历史的品种权重为 0, 不拖后全体 effective_start。
  - 任一品种实际(漂移)权重与当日最优目标偏离 > rebalance_band(默认5pp,绝对值)→ 整体再平衡回当日最优。
  - 单位净值法; 再平衡不直接改变当日 NAV(默认无成本)。
  - effective_start = max(用户start, 至少一个品种具备 min_window 历史的最早可优化日)。
无未来函数: 决策只用 ≤ 当日收益; 当日 NAV 用当日收益更新, 次日才用新权重。

性能: 用前缀和(滚动增量)预算每日窗口的均值/协方差(S1,S2 加减), 由 O(window·n²)
      降为 O(n²); 优化器接收预算 cov/mean 并以上一交易日权重热启动, 避免重复求解。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date
from typing import Callable, Optional

import numpy as np
import pandas as pd

from .optimizer import optimize


@dataclass
class Rebalance:
    trade_date: date
    reason: str
    target_weights: dict
    prev_weights: Optional[dict]
    delta: Optional[dict]
    quadrant_weights: Optional[dict]
    max_deviation: float


@dataclass
class BacktestResult:
    nav: pd.DataFrame                       # index=date, cols: nav, benchmark_nav, ret, bench_ret
    rebalances: list[Rebalance]
    effective_start: date
    latest_target: dict                     # 最近一次再平衡的目标权重
    latest_drift: dict                      # 末日漂移后的实际权重
    quadrant_weights: Optional[dict]
    end_optimal_target: dict = field(default_factory=dict)  # 末交易日滚动最优目标权重
    end_optimal_quadrant_weights: Optional[dict] = None
    corr_labels: list[str] = field(default_factory=list)
    corr_matrix: list[list[float]] = field(default_factory=list)
    cov_matrix: list[list[float]] = field(default_factory=list)
    as_of: Optional[date] = None
    # 逐日持有权重(进入当日、用于当日收益的权重): index=date, cols=资产 key。供绩效归因。
    daily_weights: pd.DataFrame = field(default_factory=pd.DataFrame)


def _union_calendar(prices: pd.DataFrame) -> list:
    """各成分有效交易日的并集(排序)。"""
    all_dates: set = set()
    for col in prices.columns:
        all_dates.update(prices[col].dropna().index)
    return sorted(all_dates)


def _filter_quadrants(
    quadrant_assets: Optional[dict[str, list[str]]], available: set[str]
) -> Optional[dict[str, list[str]]]:
    if not quadrant_assets:
        return None
    out: dict[str, list[str]] = {}
    for q, lst in quadrant_assets.items():
        sub = [x for x in lst if x in available]
        if sub:
            out[q] = sub
    return out or None


def run_backtest(
    prices: pd.DataFrame,
    benchmark: pd.Series,
    quadrant_assets: Optional[dict[str, list[str]]],
    method: str = "quadrant_inner_sharpe_outer_rp",
    ratio: str = "sharpe",
    lookback: int = 156,
    min_window: int = 60,
    max_weight: Optional[float] = None,
    rebalance_band: float = 0.05,
    risk_free: float = 0.0,
    fee_rate: float = 0.0,
    slippage_rate: float = 0.0,
    stamp_duty_rate: float = 0.0,
    trading_days: int = 244,
    user_start: Optional[date] = None,
    progress_cb: Optional[Callable[[int, int, str], None]] = None,
) -> BacktestResult:
    assets = list(prices.columns)
    if not assets:
        raise ValueError("无成分资产")
    n = len(assets)

    if min_window < 2:
        min_window = 2

    price_dates = _union_calendar(prices)
    if len(price_dates) < min_window + 2:
        raise ValueError(
            f"可用历史不足(仅 {len(price_dates)} 个交易日, 需 > {min_window + 1})"
        )

    prices_aligned = prices.reindex(price_dates)
    returns_df = prices_aligned.pct_change()

    # ---- 滚动增量矩(前缀和): 均值/协方差 O(n²) 取窗 ----
    Rv = returns_df.values.astype(float)              # (T, n), 第0行及未上市为 NaN
    validv = ~np.isnan(Rv)                            # 有效观测掩码
    R0 = np.nan_to_num(Rv, nan=0.0)
    cum1 = np.cumsum(R0, axis=0)                                       # (T, n)
    cum2 = np.cumsum(np.einsum("ti,tj->tij", R0, R0), axis=0)         # (T, n, n)
    cum_valid = np.cumsum(validv.astype(np.int64), axis=0)            # (T, n)
    asset_pos = {a: i for i, a in enumerate(assets)}

    k_min = min_window + 1

    def _win_bounds(end_idx: int) -> tuple[int, int]:
        return max(1, end_idx - lookback + 1), end_idx

    def available_assets(end_idx: int) -> list[str]:
        if end_idx < 1:
            return []
        a, b = _win_bounds(end_idx)
        m = b - a + 1
        if m < min_window:
            return []
        cnt = cum_valid[b] - (cum_valid[a - 1] if a > 0 else 0)
        return [asset for i, asset in enumerate(assets) if cnt[i] == m]

    def _moments(end_idx: int, avail: list[str]) -> tuple[np.ndarray, np.ndarray]:
        a, b = _win_bounds(end_idx)
        m = b - a + 1
        ii = [asset_pos[x] for x in avail]
        prev = a - 1
        s1 = cum1[b][ii] - (cum1[prev][ii] if prev >= 0 else 0.0)
        s2 = cum2[b][np.ix_(ii, ii)] - (cum2[prev][np.ix_(ii, ii)] if prev >= 0 else 0.0)
        mean = s1 / m
        cov = (s2 - np.outer(s1, s1) / m) / (m - 1)
        return mean, cov

    def opt(end_idx: int, warm: Optional[pd.Series] = None) -> tuple[pd.Series, Optional[dict]]:
        avail = available_assets(end_idx)
        if not avail:
            return pd.Series(0.0, index=assets), None
        mean, cov = _moments(end_idx, avail)
        a, b = _win_bounds(end_idx)
        sub = returns_df.iloc[a : b + 1][avail]
        qf = _filter_quadrants(quadrant_assets, set(avail))
        w_sub, qw = optimize(
            sub, qf, method, ratio, max_weight, risk_free, trading_days,
            cov=cov, mean=mean, x0=warm,
        )
        w = pd.Series(0.0, index=assets)
        for x in avail:
            w[x] = float(w_sub.get(x, 0.0))
        s = w.sum()
        if s > 0:
            w = w / s
        return w, qw

    k_user = (
        next((k for k, d in enumerate(price_dates) if d >= user_start), k_min)
        if user_start is not None
        else 0
    )
    start_k = max(k_min, k_user)

    k0 = None
    for k in range(start_k, len(price_dates)):
        if available_assets(k - 1):
            k0 = k
            break
    if k0 is None:
        raise ValueError("数据不足以从指定开始日回测")

    effective_start = price_dates[k0]

    bench = benchmark.reindex(price_dates).ffill()

    target0, quad0 = opt(k0 - 1)
    w_actual = target0.copy()
    last_target = target0
    prev_opt = target0
    quadrant_weights = quad0

    rebalances: list[Rebalance] = [
        Rebalance(
            trade_date=effective_start, reason="建仓",
            target_weights=_round(target0.to_dict()), prev_weights=None, delta=None,
            quadrant_weights=_round(quad0) if quad0 else None, max_deviation=0.0,
        )
    ]

    nav = 1.0
    bench_nav = 1.0
    rows = [
        {"trade_date": effective_start, "nav": 1.0, "benchmark_nav": 1.0,
         "ret": 0.0, "bench_ret": 0.0}
    ]
    # 建仓日权重(当日无收益), 记录用于归因
    weight_rows: list[dict] = [{"trade_date": effective_start, **target0.to_dict()}]

    # 交易成本: 手续费/滑点双边(买+卖), 印花税仅卖出方。
    commission_rate = max(float(fee_rate or 0.0), 0.0)
    slip_rate = max(float(slippage_rate or 0.0), 0.0)
    stamp_rate = max(float(stamp_duty_rate or 0.0), 0.0)

    total_steps = max(1, len(price_dates) - (k0 + 1))
    for step_i, k in enumerate(range(k0 + 1, len(price_dates)), start=1):
        day = price_dates[k]
        r_t = returns_df.iloc[k].reindex(assets).fillna(0.0)

        # 记录进入当日(收益结算前)的实际权重 → 当日各资产贡献 = w·r_t
        weight_rows.append({"trade_date": day, **w_actual.to_dict()})

        port_ret = float((w_actual * r_t).sum())
        nav *= 1.0 + port_ret

        grown = w_actual * (1.0 + r_t)
        s = grown.sum()
        w_actual = grown / s if s > 0 else w_actual

        b_t = bench.iloc[k]
        b_prev = bench.iloc[k - 1]
        bench_ret = float(b_t / b_prev - 1.0) if pd.notna(b_t) and pd.notna(b_prev) and b_prev else 0.0
        bench_nav *= 1.0 + bench_ret

        target, quad = opt(k, warm=prev_opt)
        prev_opt = target
        dev_s = (w_actual - target).abs()
        dev = float(dev_s.max())
        if dev > rebalance_band:
            prev = w_actual.copy()
            delta = target - prev
            buy_turnover = float(delta.clip(lower=0.0).sum())
            sell_turnover = float((-delta.clip(upper=0.0)).sum())
            turnover = buy_turnover + sell_turnover
            # 买卖双边缴手续费+滑点; 卖出单边另缴印花税。
            cost = turnover * (commission_rate + slip_rate) + sell_turnover * stamp_rate
            if cost > 0:
                nav *= max(0.0, 1.0 - cost)
                port_ret = (1.0 + port_ret) * max(0.0, 1.0 - cost) - 1.0
            trigger = dev_s.idxmax()
            drift_w = float(w_actual[trigger])
            target_w = float(target[trigger])
            band_pp = rebalance_band * 100
            rebalances.append(
                Rebalance(
                    trade_date=day,
                    reason=(
                        f"再平衡：{trigger} 实际权重 {drift_w*100:.2f}% 偏离目标 {target_w*100:.2f}%"
                        f"（{dev*100:.2f}pp > {band_pp:.0f}pp）"
                    ),
                    target_weights=_round(target.to_dict()),
                    prev_weights=_round(prev.to_dict()),
                    delta=_round(delta.to_dict()),
                    quadrant_weights=_round(quad) if quad else None,
                    max_deviation=dev,
                )
            )
            w_actual = target.copy()
            last_target = target
            quadrant_weights = quad

        rows.append(
            {"trade_date": day, "nav": nav, "benchmark_nav": bench_nav,
             "ret": port_ret, "bench_ret": bench_ret}
        )
        if progress_cb and (step_i == 1 or step_i == total_steps or step_i % 50 == 0):
            progress_cb(step_i, total_steps, f"{method} 回测 {step_i}/{total_steps} 交易日")

    nav_df = pd.DataFrame(rows).set_index("trade_date")
    daily_weights = (
        pd.DataFrame(weight_rows).set_index("trade_date").reindex(columns=assets).fillna(0.0)
    )

    last_avail = available_assets(len(price_dates) - 1)
    if len(last_avail) >= 2:
        a, b = _win_bounds(len(price_dates) - 1)
        last_win = returns_df.iloc[a : b + 1][last_avail]
        corr = last_win.corr()
        cov = last_win.cov() * trading_days
        corr_labels = last_avail
        corr_matrix = np.round(corr.values, 4).tolist()
        cov_matrix = np.round(cov.values, 6).tolist()
    else:
        corr_labels = []
        corr_matrix = []
        cov_matrix = []

    last_k = len(price_dates) - 1
    end_optimal_target, end_optimal_quad = opt(last_k, warm=prev_opt)

    return BacktestResult(
        nav=nav_df,
        rebalances=rebalances,
        effective_start=effective_start,
        latest_target=_round(last_target.to_dict()),
        latest_drift=_round(w_actual.to_dict()),
        quadrant_weights=_round(quadrant_weights) if quadrant_weights else None,
        end_optimal_target=_round(end_optimal_target.to_dict()),
        end_optimal_quadrant_weights=_round(end_optimal_quad) if end_optimal_quad else None,
        corr_labels=corr_labels,
        corr_matrix=corr_matrix,
        cov_matrix=cov_matrix,
        as_of=price_dates[-1],
        daily_weights=daily_weights,
    )


def _round(d: dict, ndigits: int = 6) -> dict:
    """四舍五入权重; NaN/Inf 归 0(存储安全, PG JSON 不接受 NaN token)。"""
    import math as _math

    out: dict = {}
    for k, v in d.items():
        try:
            fv = float(v)
        except (TypeError, ValueError):
            out[k] = v
            continue
        out[k] = 0.0 if (_math.isnan(fv) or _math.isinf(fv)) else round(fv, ndigits)
    return out
