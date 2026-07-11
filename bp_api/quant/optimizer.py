"""组合权重优化器。

输入: 窗口内日收益 DataFrame(index=日期, columns=资产), 象限映射, 方法, 比率。
输出: 权重 Series(Σ=1, 长仓) + (象限法)象限权重。

方法:
  - all_risk_parity              : 全体等风险贡献(ERC)
  - all_max_sharpe              : 全体最大夏普/索提诺
  - sharpe_sq_risk_budget       : 风险预算 ∝ 各资产夏普²(或索提诺²)
  - quadrant_inner_sharpe_outer_rp(默认): 象限内最大夏普 × 象限间风险平价(ERC)
比率: sharpe / sortino (影响最大夏普类目标与单资产风险预算)。
约束: 长仓 w>=0, Σw=1; 可选单标的上限 max_weight。

性能:
  - ERC / 风险预算用 Spinu 循环坐标下降(CCD)闭式迭代, 远快于 SLSQP 且更精确;
  - 最大夏普 / 索提诺仍用 SLSQP, 但支持 cov/mean 预算入参与上次权重热启动(x0),
    回测逐日调用时仅需单次热启动求解, 大幅减少迭代;
  - optimize 接受预计算的 cov / mean(由回测的滚动增量协方差提供), 避免每日重算。
"""

from __future__ import annotations

import os
from typing import Optional

import numpy as np
import pandas as pd
from scipy.optimize import minimize

DEFAULT_TRADING_DAYS = 244
DEFAULT_RISK_FREE = 0.0

QUADRANTS = ["overheat", "stagflation", "recovery", "recession"]


# ---------------------------------------------------------------------
# 协方差良态化: 在进入求解器前修复正定性
# ---------------------------------------------------------------------
def _regularize_cov(
    cov: np.ndarray,
    *,
    shrink: float = 0.05,
    diag_floor_rel: float = 1e-8,
    ridge_frac: float = 1e-5,
) -> np.ndarray:
    """协方差良态化: 对称化 + 对角下限 + Ledoit-Wolf 风格收缩 + Tikhonov Ridge。

    治本: 防止 N>T/多重共线性/停牌零方差导致的奇异或病态 Σ 使 SLSQP/CCD
    在零空间方向步长失控、约束振荡不收敛、产出 NaN 权重。

    - 对称化: 消除浮点不对称。
    - 对角下限: 零方差(停牌/常数)品种方差抬到 avg_var * diag_floor_rel。
    - 收缩: Σ_shrink = (1-δ)Σ + δ·avg_var·I, 抬高最小特征值(等价于向缩放单位阵收缩)。
    - Ridge: Σ + λI (λ=ridge_frac·avg_var), 兜底严格正定, 等价目标函数 L2 正则。

    正则后 λ_min ≥ δ·avg_var + λ > 0, 条件数有界; 对良态矩阵偏差 <5%。
    固定 δ 而非逐窗最优 δ* 是因为 δ* 需逐观测 x_t x_tᵀ 范数, 会破坏回测前缀和 O(n²) 滚动技巧。
    """
    c = np.asarray(cov, dtype=float)
    if c.ndim == 1:
        c = np.diag(c)
    c = (c + c.T) / 2.0
    n = c.shape[0]
    diag = np.diag(c).copy()
    avg_var = float(max(diag.mean(), 1e-12))
    floor = max(avg_var * diag_floor_rel, 1e-14)
    diag = np.maximum(diag, floor)
    np.fill_diagonal(c, diag)
    c = (1.0 - shrink) * c + shrink * avg_var * np.eye(n)
    c = c + max(ridge_frac * avg_var, 1e-14) * np.eye(n)
    return c


# ---------------------------------------------------------------------
# 基础度量
# ---------------------------------------------------------------------
def _portfolio_vol(w: np.ndarray, cov: np.ndarray) -> float:
    return float(np.sqrt(max(w @ cov @ w, 1e-18)))


def _downside_std(port: np.ndarray, mar: float) -> float:
    """下行波动(对 MAR 的下偏标准差)。"""
    downside = np.minimum(port - mar, 0.0)
    return float(np.sqrt(np.mean(downside**2)))


def _asset_ratio(returns: pd.DataFrame, ratio: str, rf_daily: float) -> pd.Series:
    """各资产单独的(日)夏普或索提诺比率。"""
    mean = returns.mean()
    if ratio == "sortino":
        dd = returns.apply(lambda col: _downside_std(col.values, rf_daily))
        denom = dd.replace(0.0, np.nan)
    else:
        denom = returns.std().replace(0.0, np.nan)
    sr = (mean - rf_daily) / denom
    return sr.fillna(0.0)


# ---------------------------------------------------------------------
# 约束求解 (SLSQP, 仅最大比率类目标使用)
# ---------------------------------------------------------------------
def _bounds(n: int, max_weight: Optional[float]) -> list[tuple[float, float]]:
    hi = 1.0 if max_weight is None else float(max_weight)
    return [(0.0, hi)] * n


def _sum1():
    return {"type": "eq", "fun": lambda x: np.sum(x) - 1.0}


def _solve(obj, n: int, max_weight: Optional[float], extra_x0: Optional[list] = None,
           single: bool = False):
    """SLSQP 求解, 取目标最小者。

    single=True 时只用 extra_x0(热启动)做单次求解; 否则等权 + 额外初值多起点。
    """
    if single and extra_x0:
        x0_list = list(extra_x0)
    else:
        x0_list = [np.ones(n) / n]
        if extra_x0:
            x0_list.extend(extra_x0)
    best = None
    maxiter = int(os.getenv("BP_OPT_MAXITER", "200") or "200")
    ftol = float(os.getenv("BP_OPT_FTOL", "1e-8") or "1e-8")
    for x0 in x0_list:
        try:
            res = minimize(
                obj, x0, method="SLSQP",
                bounds=_bounds(n, max_weight), constraints=[_sum1()],
                options={"maxiter": maxiter, "ftol": ftol},
            )
            if res.success and (best is None or res.fun < best.fun):
                best = res
        except Exception:  # noqa: BLE001
            continue
    return best


# ---------------------------------------------------------------------
# 风险预算 / ERC: Spinu 循环坐标下降 (CCD)
# ---------------------------------------------------------------------
def risk_budget_ccd(
    cov: np.ndarray,
    budgets: np.ndarray,
    max_weight: Optional[float] = None,
    max_iter: int = 500,
    tol: float = 1e-10,
) -> np.ndarray:
    """风险贡献按 budgets 比例分配(长仓)。

    求解 min 0.5 wᵀΣw - Σ b_i ln(w_i), w>0; 其稳定点处各资产风险贡献 ∝ b_i。
    坐标更新(闭式): w_i = (-a_i + sqrt(a_i² + 4 σ_ii b_i)) / (2 σ_ii),
    其中 a_i = Σ_{j≠i} σ_ij w_j。迭代收敛后归一化。
    """
    n = cov.shape[0]
    if n == 1:
        return np.array([1.0])

    b = np.asarray(budgets, dtype=float)
    b_sum = b.sum()
    b = b / b_sum if b_sum > 0 else np.ones(n) / n

    sigma = np.asarray(cov, dtype=float)
    diag = np.diag(sigma).copy()
    diag[diag < 1e-18] = 1e-18  # 防零方差

    inv_vol = 1.0 / np.sqrt(diag)
    w = inv_vol / inv_vol.sum()  # 逆波动率初值

    for _ in range(max_iter):
        w_old = w.copy()
        for i in range(n):
            a_i = float(sigma[i] @ w) - diag[i] * w[i]  # Σ_{j≠i} σ_ij w_j
            w[i] = (-a_i + np.sqrt(a_i * a_i + 4.0 * diag[i] * b[i])) / (2.0 * diag[i])
        # 目标按比例不变, 用相对变化判敛
        if np.max(np.abs(w - w_old)) < tol * max(1.0, float(np.max(w))):
            break

    w = _normalize(np.clip(w, 0.0, None))
    if max_weight is not None:
        w = _apply_max_weight(pd.Series(w), max_weight).values
    return w


def risk_parity_weights(cov: np.ndarray, max_weight: Optional[float] = None) -> np.ndarray:
    """等风险贡献(ERC) = 等预算风险预算。"""
    n = cov.shape[0]
    if n == 1:
        return np.array([1.0])
    return risk_budget_ccd(cov, np.ones(n), max_weight)


def risk_budget_weights(
    cov: np.ndarray, budgets: np.ndarray, max_weight: Optional[float] = None
) -> np.ndarray:
    """风险贡献按 budgets 比例分配(向后兼容封装, 内部走 CCD)。"""
    return risk_budget_ccd(cov, budgets, max_weight)


# ---------------------------------------------------------------------
# 最大夏普 / 索提诺 (SLSQP + 可选预算 cov/mean + 热启动 x0)
# ---------------------------------------------------------------------
def max_ratio_weights(
    returns: pd.DataFrame,
    ratio: str,
    rf_daily: float,
    max_weight: Optional[float] = None,
    *,
    cov: Optional[np.ndarray] = None,
    mean: Optional[np.ndarray] = None,
    x0: Optional[np.ndarray] = None,
) -> np.ndarray:
    """最大化组合夏普 / 索提诺比率。

    cov/mean 可由外部(滚动协方差)预算; sortino 仍需窗口日收益矩阵。
    x0 给定时仅做单次热启动求解(逐日回测相邻解几乎不变, 收敛极快)。
    """
    n = returns.shape[1]
    if n == 1:
        return np.array([1.0])
    mean_v = returns.mean().values if mean is None else np.asarray(mean, dtype=float)
    # 仅当内部自算协方差时正则; 被 optimize 传入时已正则, 不重复。
    cov_m = _regularize_cov(returns.cov().values) if cov is None else np.asarray(cov, dtype=float)
    rmat = returns.values

    if ratio == "sortino":
        def obj(w):
            port = rmat @ w
            dd = _downside_std(port, rf_daily)
            if dd < 1e-12:
                return 1e6
            return -float((w @ mean_v - rf_daily) / dd)
    else:
        def obj(w):
            vol = _portfolio_vol(w, cov_m)
            if vol < 1e-12:
                return 1e6
            return -float((w @ mean_v - rf_daily) / vol)

    inv_vol = 1.0 / np.sqrt(np.clip(np.diag(cov_m), 1e-18, None))
    warm = None
    if x0 is not None:
        x0 = np.clip(np.asarray(x0, dtype=float), 0.0, None)
        s = x0.sum()
        if s > 0:
            warm = x0 / s
    if warm is not None:
        res = _solve(obj, n, max_weight, extra_x0=[warm], single=True)
        if res is None:  # 热启动失败 → 回退多起点
            res = _solve(obj, n, max_weight, extra_x0=[inv_vol / inv_vol.sum()])
    else:
        res = _solve(obj, n, max_weight, extra_x0=[inv_vol / inv_vol.sum()])
    # SLSQP 不收敛(res.x 含 NaN)或失败时, 回退到 inv_vol(等风险近似), 避免权重 NaN 污染回测。
    w = res.x if (res is not None and np.all(np.isfinite(res.x))) else (inv_vol / inv_vol.sum())
    return _normalize(np.clip(w, 0, None))


# ---------------------------------------------------------------------
# 工具
# ---------------------------------------------------------------------
def _normalize(w: np.ndarray) -> np.ndarray:
    s = w.sum()
    if s <= 0:
        return np.ones_like(w) / len(w)
    return w / s


def _apply_max_weight(w: pd.Series, max_weight: Optional[float]) -> pd.Series:
    """迭代地把超过上限的权重削平并把多余分给未触顶的标的。"""
    if max_weight is None or len(w) * max_weight < 0.999:
        return w
    w = w.copy()
    for _ in range(100):
        over = w[w > max_weight]
        if over.empty:
            break
        excess = (over - max_weight).sum()
        w[w > max_weight] = max_weight
        room = w[w < max_weight]
        if room.empty:
            break
        w[room.index] += excess * room / room.sum()
    return _series_normalize(w)


def _series_normalize(w: pd.Series) -> pd.Series:
    s = w.sum()
    return w / s if s > 0 else pd.Series(1.0 / len(w), index=w.index)


def _x0_subarray(x0, cols: list[str]) -> Optional[np.ndarray]:
    """把全宇宙权重(Series 或 dict)切到 cols 顺序的热启动数组; 无则 None。"""
    if x0 is None:
        return None
    if hasattr(x0, "get"):
        arr = np.array([float(x0.get(c, 0.0)) for c in cols], dtype=float)
        return arr if arr.sum() > 0 else None
    return None


# ---------------------------------------------------------------------
# 顶层入口
# ---------------------------------------------------------------------
def build_quadrant_assets(assets: list[dict]) -> dict[str, list[str]]:
    """从组合成分行构建象限→资产列表; 同一资产可出现在多个象限。"""
    out: dict[str, list[str]] = {q: [] for q in QUADRANTS}
    for a in assets:
        q = a.get("quadrant")
        if q not in out:
            continue
        key = a.get("key") or f"{a['symbol']}@{a['source']}"
        if key not in out[q]:
            out[q].append(key)
    return out


def optimize(
    returns: pd.DataFrame,
    quadrant_assets: Optional[dict[str, list[str]]] = None,
    method: str = "quadrant_inner_sharpe_outer_rp",
    ratio: str = "sharpe",
    max_weight: Optional[float] = None,
    risk_free: float = DEFAULT_RISK_FREE,
    trading_days: int = DEFAULT_TRADING_DAYS,
    *,
    cov: Optional[np.ndarray] = None,
    mean: Optional[np.ndarray] = None,
    x0=None,
) -> tuple[pd.Series, Optional[dict[str, float]]]:
    """返回 (各资产权重 Series, 象限权重 dict 或 None)。

    cov/mean: 可由外部预算(列顺序须与 returns.columns 一致), 缺省则从 returns 计算。
    x0: 上次权重(Series/dict, 按资产 key), 作为最大比率类目标的热启动。
    """
    assets = list(returns.columns)
    if not assets:
        raise ValueError("空收益矩阵, 无法优化")
    rf_daily = risk_free / trading_days

    if len(assets) == 1:
        return pd.Series([1.0], index=assets), None

    cov_m = _regularize_cov(returns.cov().values if cov is None else np.asarray(cov, dtype=float))
    mean_v = returns.mean().values if mean is None else np.asarray(mean, dtype=float)
    idx = {a: i for i, a in enumerate(assets)}

    quad_weights: Optional[dict[str, float]] = None

    if method == "all_risk_parity":
        w = pd.Series(risk_parity_weights(cov_m, max_weight), index=assets)

    elif method == "all_max_sharpe":
        w = pd.Series(
            max_ratio_weights(
                returns, ratio, rf_daily, max_weight,
                cov=cov_m, mean=mean_v, x0=_x0_subarray(x0, assets),
            ),
            index=assets,
        )

    elif method == "sharpe_sq_risk_budget":
        sr = _asset_ratio(returns, ratio, rf_daily)
        budgets = np.clip(sr.values, 0, None) ** 2
        if budgets.sum() <= 1e-12:
            budgets = np.ones(len(assets))
        w = pd.Series(risk_budget_ccd(cov_m, budgets, max_weight), index=assets)

    elif method == "quadrant_inner_sharpe_outer_rp":
        if not quadrant_assets:
            raise ValueError("象限法需要 quadrant_assets")
        # 1) 象限内最大夏普 → 内部权重 v_q
        inner: dict[str, pd.Series] = {}
        quad_ret = {}
        for q in QUADRANTS:
            q_assets = [a for a in quadrant_assets.get(q, []) if a in assets]
            if not q_assets:
                continue
            if len(q_assets) == 1:
                v = pd.Series([1.0], index=q_assets)
            else:
                ii = [idx[a] for a in q_assets]
                sub_cov = cov_m[np.ix_(ii, ii)]
                sub_mean = mean_v[ii]
                sub = returns[q_assets]
                v = pd.Series(
                    max_ratio_weights(
                        sub, ratio, rf_daily, max_weight,
                        cov=sub_cov, mean=sub_mean, x0=_x0_subarray(x0, q_assets),
                    ),
                    index=q_assets,
                )
            inner[q] = v
            quad_ret[q] = (returns[q_assets] * v.values).sum(axis=1)

        active_q = list(quad_ret.keys())
        if len(active_q) == 1:
            u_arr = np.array([1.0])
        else:
            quad_df = pd.DataFrame(quad_ret)
            u_arr = risk_parity_weights(_regularize_cov(quad_df.cov().values))
        u = pd.Series(u_arr, index=active_q)
        quad_weights = {q: float(u[q]) for q in active_q}

        # 2) 合成最终权重 w_i = u_q · v_q,i
        w = pd.Series(0.0, index=assets)
        for q in active_q:
            for a, vi in inner[q].items():
                w[a] += u[q] * vi

    else:
        raise ValueError(f"未知优化方法: {method}")

    # 清洗 NaN/Inf(退化协方差下个别方法可能产生), 再归一; 不影响正常回测数值。
    w = w.fillna(0.0)
    w = _apply_max_weight(_series_normalize(w.clip(lower=0)), max_weight)
    return w, quad_weights
