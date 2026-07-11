"""绩效归因: 组合收益率拆解(Brinson 思想 + 四桶分解)。

对组合期间收益做拆解:
  - 系统性 Beta(基准)  : β·r_b, β = Cov(r_p, r_b)/Var(r_b)
  - 截面选择(选品)     : Σ_i w̄_i r_{i,t} − β·r_b    (按"平均配置"持有的超额, 体现选了哪些资产)
  - 时序调仓(择时)     : Σ_i (w_{i,t}−w̄_i) r_{i,t}  (动态偏离平均权重的增量, 体现调仓价值)
  - 残差               : 实际净值总收益 − 上述(税前权重)解释总收益 ≈ 交易成本/复利口径差

日度上 系统性+截面+时序 == 税前组合日收益(代数恒等); 跨日用 Carino 对数链接到几何总收益,
使各桶可加且合计=税前几何总收益; 残差吸收实际净值(含费/滑点)与税前解释值之差。

逐资产: 每个资产的 Carino 链接累计贡献, 拆为静态(平均权重)与调仓两部分。
逐调仓: 每个再平衡持有区间的几何收益与对总收益的(链接)加性贡献。
"""

from __future__ import annotations

from typing import Optional

import numpy as np
import pandas as pd


def _carino_coeffs(daily_rets: np.ndarray, total: float) -> np.ndarray:
    """Carino 对数链接系数 k_t, 使 Σ_t k_t · x_t 将算术日度量链接为几何累计。"""
    daily = np.asarray(daily_rets, dtype=float)
    denom = np.log1p(total) / total if abs(total) > 1e-12 else 1.0
    with np.errstate(divide="ignore", invalid="ignore"):
        num = np.where(np.abs(daily) < 1e-12, 1.0, np.log1p(daily) / daily)
    num = np.nan_to_num(num, nan=1.0, posinf=1.0, neginf=1.0)
    return num / denom if denom != 0 else num


def _empty() -> dict:
    return {
        "summary": {
            "total_return": 0.0, "beta": 0.0, "systematic": 0.0,
            "selection": 0.0, "timing": 0.0, "residual": 0.0,
        },
        "assets": [],
        "rebalances": [],
    }


def compute_attribution(
    daily_weights: pd.DataFrame,
    asset_returns: pd.DataFrame,
    bench_ret: Optional[pd.Series],
    nav: pd.Series,
    rebalances: Optional[list[dict]] = None,
    name_map: Optional[dict[str, str]] = None,
    quad_map: Optional[dict[str, list]] = None,
) -> dict:
    """返回 {summary, assets[], rebalances[]}。

    daily_weights: index=交易日(含建仓日), columns=资产 key, 值=进入当日(结算前)的实际权重。
    asset_returns: 各资产日简单收益(宽表), 用于按日 contribution = w·r。
    bench_ret    : 组合配置基准的日收益(用于 β); 可为 None。
    nav          : 实际组合单位净值序列(含费/滑点), 用于总收益与逐调仓区间收益。
    """
    name_map = name_map or {}
    quad_map = quad_map or {}

    if daily_weights is None or daily_weights.shape[0] < 2:
        return _empty()

    assets = list(daily_weights.columns)
    # 建仓日无收益, 取其后的进入权重与对应日收益(与回测口径一致)
    W_df = daily_weights.iloc[1:]
    dates = W_df.index
    if len(dates) < 1 or not assets:
        return _empty()

    W = W_df.values.astype(float)                                            # (T, n)
    R = asset_returns.reindex(index=dates, columns=assets).fillna(0.0).values  # (T, n)

    contrib = W * R                       # (T, n) 各资产日贡献
    rp = contrib.sum(axis=1)              # (T,) 税前组合日收益
    explained_total = float(np.prod(1.0 + rp) - 1.0)

    if bench_ret is not None:
        rb = pd.Series(bench_ret).reindex(dates).astype(float).fillna(0.0).values
    else:
        rb = np.zeros(len(dates))

    var_b = float(np.var(rb))
    beta = float(np.cov(rp, rb)[0, 1] / var_b) if var_b > 1e-18 and len(rp) > 1 else 0.0

    wbar = W.mean(axis=0)                  # (n,) 平均(战略)权重

    systematic_t = beta * rb
    selection_t = (wbar * R).sum(axis=1) - beta * rb
    timing_t = ((W - wbar) * R).sum(axis=1)

    k = _carino_coeffs(rp, explained_total)
    sys_c = float(np.sum(k * systematic_t))
    sel_c = float(np.sum(k * selection_t))
    tim_c = float(np.sum(k * timing_t))

    # 实际净值总收益(含费/滑点); 残差 = 实际 − 税前解释
    nav = pd.Series(nav).dropna()
    port_total = float(nav.iloc[-1] / nav.iloc[0] - 1.0) if len(nav) > 1 else explained_total
    residual = port_total - (sys_c + sel_c + tim_c)

    summary = {
        "total_return": port_total,
        "beta": beta,
        "systematic": sys_c,
        "selection": sel_c,
        "timing": tim_c,
        "residual": residual,
    }

    # 逐资产: Carino 链接累计贡献 + 静态/调仓拆分 + 资产自身区间收益
    asset_total = (k[:, None] * contrib).sum(axis=0)
    asset_static = (k[:, None] * (wbar * R)).sum(axis=0)
    asset_timing = (k[:, None] * ((W - wbar) * R)).sum(axis=0)
    asset_self_ret = np.prod(1.0 + R, axis=0) - 1.0

    assets_out = [
        {
            "key": a,
            "name": name_map.get(a, a),
            "quadrants": quad_map.get(a, []),
            "avg_weight": float(wbar[i]),
            "asset_return": float(asset_self_ret[i]),
            "contribution": float(asset_total[i]),
            "static": float(asset_static[i]),
            "timing": float(asset_timing[i]),
        }
        for i, a in enumerate(assets)
    ]
    assets_out.sort(key=lambda x: -x["contribution"])

    # 逐调仓: 每个再平衡持有区间的几何收益 + 链接加性贡献
    rebalances_out: list[dict] = []
    if rebalances:
        rb_dates = [pd.Timestamp(r["trade_date"]) for r in rebalances]
        nav_idx = pd.to_datetime(nav.index)
        nav_vals = nav.values.astype(float)
        bounds = rb_dates + [nav_idx[-1]]
        interval_rets: list[float] = []
        spans: list[tuple] = []
        for i in range(len(rb_dates)):
            start = bounds[i]
            end = bounds[i + 1]
            si = int(np.searchsorted(nav_idx.values, np.datetime64(start)))
            ei = int(np.searchsorted(nav_idx.values, np.datetime64(end)))
            si = min(max(si, 0), len(nav_vals) - 1)
            ei = min(max(ei, 0), len(nav_vals) - 1)
            r_int = float(nav_vals[ei] / nav_vals[si] - 1.0) if nav_vals[si] else 0.0
            interval_rets.append(r_int)
            spans.append((rebalances[i].get("trade_date"),
                          rebalances[i + 1].get("trade_date") if i + 1 < len(rebalances) else nav.index[-1]))
        ik = _carino_coeffs(np.array(interval_rets), port_total)
        for i, r_int in enumerate(interval_rets):
            rb = rebalances[i]
            rebalances_out.append({
                "trade_date": str(rb.get("trade_date")),
                "end_date": str(spans[i][1]),
                "reason": rb.get("reason"),
                "period_return": r_int,
                "contribution": float(ik[i] * r_int),
            })

    return {"summary": summary, "assets": assets_out, "rebalances": rebalances_out}
