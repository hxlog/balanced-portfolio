"""定价数值内核 (纯 numpy/scipy, clean-room)。

- simulate_gbm_paths: 几何布朗运动离散路径, 支持对偶变量方差缩减 + 固定种子(公共随机数)。
- price_*_mc: 四类产品的路径依赖 payoff (向量化)。
- barrier_analytic / airbag_analytic: 单边障碍/气囊闭式解 (Black-Scholes-Merton)。

价格单位与标的指数点位一致(如 6000), 障碍/行权价为绝对点位。名义本金按 (payoff/s0)×notional 折算。
"""

from __future__ import annotations

import numpy as np
from scipy.stats import norm

from .enums import CallPut, InOut, UpDown


# ---------------------------------------------------------------------------
# 路径模拟
# ---------------------------------------------------------------------------
def simulate_gbm_paths(
    spot: float,
    r: float,
    q: float,
    vol: float,
    n_steps: int,
    n_paths: int,
    dt: float,
    rng: "np.random.Generator | None" = None,
    seed: int | None = 42,
    antithetic: bool = True,
) -> np.ndarray:
    """返回形状 (n_paths, n_steps+1) 的价格路径, 第 0 列恒为 spot(估值日)。

    传入 rng 时使用该发生器(便于分批 + 公共随机数); 否则由 seed 新建。
    """
    if n_steps <= 0:
        return np.full((n_paths, 1), spot, dtype=float)
    if rng is None:
        rng = np.random.default_rng(seed)
    if antithetic:
        half = (n_paths + 1) // 2
        z = rng.standard_normal((half, n_steps))
        z = np.concatenate([z, -z], axis=0)[:n_paths]
    else:
        z = rng.standard_normal((n_paths, n_steps))
    drift = (r - q - 0.5 * vol * vol) * dt
    diffusion = vol * np.sqrt(dt)
    log_increments = drift + diffusion * z
    np.cumsum(log_increments, axis=1, out=log_increments)
    prices = spot * np.exp(log_increments)
    s0_col = np.full((n_paths, 1), spot, dtype=float)
    return np.concatenate([s0_col, prices], axis=1)


def mc_expectation(
    *,
    spot: float,
    r: float,
    q: float,
    vol: float,
    n_steps: int,
    dt: float,
    n_paths: int,
    payoff_fn,
    seed: int = 42,
    batch: int = 20000,
    antithetic: bool = True,
    want_mean_path: bool = False,
):
    """分批模拟并对 payoff_fn(paths)->每路径收益数组 求均值, 内存受控。

    使用单一 rng 顺序抽样 → 只要 (n_paths, n_steps, batch) 不变, 不同 spot/vol/r
    重定价共享同一组随机数(公共随机数), Greeks 更稳定。
    """
    rng = np.random.default_rng(seed)
    total = 0.0
    count = 0
    path_sum = np.zeros(n_steps + 1, dtype=float) if want_mean_path else None
    remaining = n_paths
    while remaining > 0:
        b = min(batch, remaining)
        paths = simulate_gbm_paths(spot, r, q, vol, n_steps, b, dt, rng=rng, antithetic=antithetic)
        pay = payoff_fn(paths)
        total += float(np.sum(pay))
        count += b
        if want_mean_path:
            path_sum += paths.sum(axis=0)
        remaining -= b
    mean_pv = total / count if count else 0.0
    mean_path = (path_sum / count) if want_mean_path and count else None
    return mean_pv, mean_path


# ---------------------------------------------------------------------------
# 雪球 Snowball (含红利/期末票息)
# ---------------------------------------------------------------------------
def snowball_payoff(
    paths: np.ndarray,
    *,
    ko_obs_idx: np.ndarray,
    ko_barrier: float,
    ko_coupon_amounts: np.ndarray,   # 每个敲出观察日对应的敲出票息金额(已按 ACT/365 计息+名义)
    ko_discounts: np.ndarray,        # 每个敲出观察日的折现因子
    ki_barrier: float,
    ki_strike: float,
    s0: float,
    notional: float,
    maturity_div_amount: float,      # 红利/期末票息金额(未敲出未敲入到期)
    maturity_discount: float,
    already_ki: bool = False,
) -> np.ndarray:
    """返回每条路径的折现收益(货币单位)。"""
    n = paths.shape[0]
    result = np.zeros(n, dtype=float)
    done = np.zeros(n, dtype=bool)

    for i, od in enumerate(ko_obs_idx):
        if od <= 0 or od >= paths.shape[1]:
            continue
        hit = (~done) & (paths[:, od] >= ko_barrier)
        result[hit] = ko_coupon_amounts[i] * ko_discounts[i]
        done |= hit

    rem = ~done
    if already_ki:
        ki = np.ones(n, dtype=bool)
    else:
        ki = (paths[:, 1:] < ki_barrier).any(axis=1)

    st = paths[:, -1]
    rem_ki = rem & ki
    rem_noki = rem & ~ki
    result[rem_ki] = -np.maximum(ki_strike - st[rem_ki], 0.0) / s0 * notional * maturity_discount
    result[rem_noki] = maturity_div_amount * maturity_discount
    return result


# ---------------------------------------------------------------------------
# 凤凰 Phoenix (派息障碍逐期派息 + 敲出终止 + 敲入到期承损)
# ---------------------------------------------------------------------------
def phoenix_payoff(
    paths: np.ndarray,
    *,
    obs_idx: np.ndarray,             # 敲出/派息观察日下标(升序)
    ko_barrier: float,
    coupon_barrier: float,           # 派息障碍 barrier_yield
    period_coupon_amount: float,     # 每期派息金额(固定)
    period_discounts: np.ndarray,    # 每个观察日的折现因子
    ki_barrier: float,
    ki_strike: float,
    s0: float,
    notional: float,
    maturity_discount: float,
    already_ki: bool = False,
) -> np.ndarray:
    n = paths.shape[0]
    coupons_pv = np.zeros(n, dtype=float)
    done = np.zeros(n, dtype=bool)

    for i, od in enumerate(obs_idx):
        if od <= 0 or od >= paths.shape[1]:
            continue
        alive = ~done
        s = paths[:, od]
        pay = alive & (s >= coupon_barrier)
        coupons_pv[pay] += period_coupon_amount * period_discounts[i]
        ko = alive & (s >= ko_barrier)
        done |= ko

    if already_ki:
        ki = np.ones(n, dtype=bool)
    else:
        ki = (paths[:, 1:] < ki_barrier).any(axis=1)

    st = paths[:, -1]
    loss = np.zeros(n, dtype=float)
    rem_ki = (~done) & ki
    loss[rem_ki] = -np.maximum(ki_strike - st[rem_ki], 0.0) / s0 * notional * maturity_discount
    return coupons_pv + loss


# ---------------------------------------------------------------------------
# 安全气囊 Airbag
# ---------------------------------------------------------------------------
def airbag_payoff(
    paths: np.ndarray,
    *,
    strike: float,
    barrier: float,                  # 下方敲入障碍
    knockin_parti: float,            # 敲入后下行参与率
    call_parti: float,               # 未敲入上行参与率
    reset_call_parti: float,         # 敲入后上行参与率
    s0: float,
    notional: float,
    discount: float,
    discrete: bool = True,
) -> np.ndarray:
    st = paths[:, -1]
    if discrete:
        touched = (paths[:, 1:] <= barrier).any(axis=1)
    else:
        touched = (paths.min(axis=1) <= barrier)
    up = st >= strike
    payoff = np.zeros(paths.shape[0], dtype=float)
    payoff[~touched & up] = call_parti * (st[~touched & up] - strike)
    payoff[touched & up] = reset_call_parti * (st[touched & up] - strike)
    payoff[touched & ~up] = knockin_parti * (st[touched & ~up] - strike)
    return payoff / s0 * notional * discount


# ---------------------------------------------------------------------------
# 单边障碍期权 Barrier
# ---------------------------------------------------------------------------
def barrier_payoff(
    paths: np.ndarray,
    *,
    strike: float,
    barrier: float,
    rebate: float,                   # 货币单位(已折算名义)
    parti: float,
    updown: UpDown,
    inout: InOut,
    callput: CallPut,
    s0: float,
    notional: float,
    discount: float,
    discrete: bool = True,
) -> np.ndarray:
    st = paths[:, -1]
    monitored = paths[:, 1:] if discrete else paths
    if updown == UpDown.UP:
        touched = (monitored >= barrier).any(axis=1) if discrete else (monitored.max(axis=1) >= barrier)
    else:
        touched = (monitored <= barrier).any(axis=1) if discrete else (monitored.min(axis=1) <= barrier)

    if callput == CallPut.CALL:
        intrinsic = np.maximum(st - strike, 0.0)
    else:
        intrinsic = np.maximum(strike - st, 0.0)

    payoff = np.zeros(paths.shape[0], dtype=float)
    if inout == InOut.OUT:
        alive = ~touched
        payoff[alive] = parti * intrinsic[alive] / s0 * notional
        payoff[touched] = rebate
    else:  # IN
        alive = touched
        payoff[alive] = parti * intrinsic[alive] / s0 * notional
        payoff[~touched] = rebate
    return payoff * discount


# ---------------------------------------------------------------------------
# 障碍期权闭式解 (Black-Scholes, Reiner-Rubinstein / Haug)
# ---------------------------------------------------------------------------
def barrier_analytic(
    *,
    s: float,
    strike: float,
    barrier: float,
    rebate: float,
    updown: UpDown,
    inout: InOut,
    callput: CallPut,
    r: float,
    q: float,
    vol: float,
    t: float,
) -> float:
    """单位名义(每 1 点标的)的障碍期权价值; 连续观察假设。"""
    if t <= 0 or vol <= 0:
        # 到期内在价值
        intr = max(s - strike, 0.0) if callput == CallPut.CALL else max(strike - s, 0.0)
        knocked = (s >= barrier) if updown == UpDown.UP else (s <= barrier)
        if inout == InOut.OUT:
            return intr if not knocked else rebate
        return intr if knocked else rebate

    phi = 1.0 if callput == CallPut.CALL else -1.0
    eta = 1.0 if updown == UpDown.DOWN else -1.0
    sqrt_t = np.sqrt(t)
    mu = (r - q - 0.5 * vol * vol) / (vol * vol)
    lam = np.sqrt(mu * mu + 2.0 * r / (vol * vol))
    H, K, S = barrier, strike, s

    x1 = np.log(S / K) / (vol * sqrt_t) + (1 + mu) * vol * sqrt_t
    x2 = np.log(S / H) / (vol * sqrt_t) + (1 + mu) * vol * sqrt_t
    y1 = np.log(H * H / (S * K)) / (vol * sqrt_t) + (1 + mu) * vol * sqrt_t
    y2 = np.log(H / S) / (vol * sqrt_t) + (1 + mu) * vol * sqrt_t
    z = np.log(H / S) / (vol * sqrt_t) + lam * vol * sqrt_t

    edq = np.exp(-q * t)
    edr = np.exp(-r * t)

    def N(x):
        return norm.cdf(x)

    A = phi * S * edq * N(phi * x1) - phi * K * edr * N(phi * x1 - phi * vol * sqrt_t)
    B = phi * S * edq * N(phi * x2) - phi * K * edr * N(phi * x2 - phi * vol * sqrt_t)
    C = (phi * S * edq * (H / S) ** (2 * (mu + 1)) * N(eta * y1)
         - phi * K * edr * (H / S) ** (2 * mu) * N(eta * y1 - eta * vol * sqrt_t))
    D = (phi * S * edq * (H / S) ** (2 * (mu + 1)) * N(eta * y2)
         - phi * K * edr * (H / S) ** (2 * mu) * N(eta * y2 - eta * vol * sqrt_t))
    E = rebate * edr * (N(eta * x2 - eta * vol * sqrt_t)
                        - (H / S) ** (2 * mu) * N(eta * y2 - eta * vol * sqrt_t))
    F = rebate * ((H / S) ** (mu + lam) * N(eta * z)
                  + (H / S) ** (mu - lam) * N(eta * z - 2 * eta * lam * vol * sqrt_t))

    up = updown == UpDown.UP
    call = callput == CallPut.CALL
    in_ = inout == InOut.IN
    K_gt_H = K > H

    if not up and in_ and call:        # cdi
        val = (C + E) if K_gt_H else (A - B + D + E)
    elif up and in_ and call:          # cui
        val = (A + E) if K_gt_H else (B - C + D + E)
    elif not up and in_ and not call:  # pdi
        val = (B - C + D + E) if K_gt_H else (A + E)
    elif up and in_ and not call:      # pui
        val = (A - B + D + E) if K_gt_H else (C + E)
    elif not up and not in_ and call:  # cdo
        val = (A - C + F) if K_gt_H else (B - D + F)
    elif up and not in_ and call:      # cuo
        val = (F) if K_gt_H else (A - B + C - D + F)
    elif not up and not in_ and not call:  # pdo
        val = (A - B + C - D + F) if K_gt_H else (F)
    else:                              # puo
        val = (B - D + F) if K_gt_H else (A - C + F)
    return float(max(val, 0.0))


def vanilla_bs(*, s, strike, r, q, vol, t, callput: CallPut) -> float:
    if t <= 0 or vol <= 0:
        return max(s - strike, 0.0) if callput == CallPut.CALL else max(strike - s, 0.0)
    d1 = (np.log(s / strike) + (r - q + 0.5 * vol * vol) * t) / (vol * np.sqrt(t))
    d2 = d1 - vol * np.sqrt(t)
    if callput == CallPut.CALL:
        return float(s * np.exp(-q * t) * norm.cdf(d1) - strike * np.exp(-r * t) * norm.cdf(d2))
    return float(strike * np.exp(-r * t) * norm.cdf(-d2) - s * np.exp(-q * t) * norm.cdf(-d1))


def airbag_analytic(
    *,
    s: float,
    strike: float,
    barrier: float,
    knockin_parti: float,
    call_parti: float,
    reset_call_parti: float,
    r: float,
    q: float,
    vol: float,
    t: float,
) -> float:
    """气囊闭式解(连续观察, 障碍复制法), 单位名义(每 1 点标的)。

    分解:
      未敲入上行 = call_parti × 下出看涨(strike, barrier)
      敲入后上行 = reset_call_parti × 下入看涨(strike, barrier)
      敲入后下行 = knockin_parti × [ 下入(标的-strike) ] = knockin_parti×(下入远期 - strike×下入数字)
                 ≈ knockin_parti × ( 下入看涨 - 下入看跌 )
    """
    cdo = barrier_analytic(s=s, strike=strike, barrier=barrier, rebate=0.0,
                           updown=UpDown.DOWN, inout=InOut.OUT, callput=CallPut.CALL,
                           r=r, q=q, vol=vol, t=t)
    cdi = barrier_analytic(s=s, strike=strike, barrier=barrier, rebate=0.0,
                           updown=UpDown.DOWN, inout=InOut.IN, callput=CallPut.CALL,
                           r=r, q=q, vol=vol, t=t)
    pdi = barrier_analytic(s=s, strike=strike, barrier=barrier, rebate=0.0,
                           updown=UpDown.DOWN, inout=InOut.IN, callput=CallPut.PUT,
                           r=r, q=q, vol=vol, t=t)
    return float(call_parti * cdo + reset_call_parti * cdi - knockin_parti * pdi)


# ---------------------------------------------------------------------------
# 积分法 (数值积分 / Quadrature) — 对数价格网格 + 高斯转移核 + 后向归纳
# ---------------------------------------------------------------------------
def _log_grid(spot: float, vol: float, t: float, n_points: int = 801) -> np.ndarray:
    """对数价格网格, 覆盖 ±4σ。"""
    if t <= 0 or vol <= 0:
        return np.array([np.log(max(spot, 1e-8))])
    std = vol * np.sqrt(t)
    lo = np.log(max(spot, 1e-8)) - 4.0 * std
    hi = np.log(spot) + 4.0 * std
    return np.linspace(lo, hi, n_points)


def _transition_matrix(
    ln_s: np.ndarray, dt: float, r: float, q: float, vol: float
) -> np.ndarray:
    """从 t 到 t+dt 的对数正态转移核矩阵 shape (n, n)。

    T[i, j] = P(ln_s[j] → ln_s[i]); 列归一化使 sum_i T[i,j] = 1。
    后向期望: E[V | j] = sum_i T[i,j] V[i] = (T.T @ V)[j]。
    """
    n = len(ln_s)
    if dt <= 0:
        return np.eye(n)
    drift = (r - q - 0.5 * vol * vol) * dt
    std = vol * np.sqrt(dt)
    # T[i,j] = dens of going from ln_s[j] at t to ln_s[i] at t+dt
    diff = ln_s[:, None] - ln_s[None, :] - drift
    kernel = np.exp(-0.5 * (diff / std) ** 2) / (std * np.sqrt(2 * np.pi))
    dx = ln_s[1] - ln_s[0] if n > 1 else 1.0
    kernel *= dx
    col_sums = kernel.sum(axis=0, keepdims=True)
    col_sums = np.where(col_sums > 0, col_sums, 1.0)
    return kernel / col_sums


def vanilla_quad(
    *, s: float, strike: float, r: float, q: float, vol: float, t: float,
    callput: CallPut, n_points: int = 801,
) -> float:
    """Vanilla 欧式期权数值积分 (辛普森/梯形 on log grid × 对数正态密度)。"""
    if t <= 0 or vol <= 0:
        return vanilla_bs(s=s, strike=strike, r=r, q=q, vol=vol, t=t, callput=callput)
    ln_s = _log_grid(s, vol, t, n_points)
    spots = np.exp(ln_s)
    if callput == CallPut.CALL:
        payoff = np.maximum(spots - strike, 0.0)
    else:
        payoff = np.maximum(strike - spots, 0.0)
    # 对数正态密度 at T
    mu = np.log(s) + (r - q - 0.5 * vol * vol) * t
    std = vol * np.sqrt(t)
    pdf = np.exp(-0.5 * ((ln_s - mu) / std) ** 2) / (std * np.sqrt(2 * np.pi))
    dx = ln_s[1] - ln_s[0]
    integral = float(np.sum(payoff * pdf) * dx)
    return integral * np.exp(-r * t)


def barrier_quad(
    *,
    s: float,
    strike: float,
    barrier: float,
    rebate: float,
    updown: UpDown,
    inout: InOut,
    callput: CallPut,
    r: float,
    q: float,
    vol: float,
    t: float,
    n_steps: int = 252,
    n_points: int = 401,
) -> float:
    """单边障碍期权数值积分 (离散日度观察, 后向归纳)。"""
    if t <= 0 or vol <= 0:
        return barrier_analytic(
            s=s, strike=strike, barrier=barrier, rebate=rebate,
            updown=updown, inout=inout, callput=callput, r=r, q=q, vol=vol, t=t,
        )
    dt = t / n_steps
    ln_s = _log_grid(s, vol, t, n_points)
    spots = np.exp(ln_s)
    if callput == CallPut.CALL:
        terminal = np.maximum(spots - strike, 0.0)
    else:
        terminal = np.maximum(strike - spots, 0.0)

    # 终端障碍条件
    if updown == UpDown.UP:
        touched = spots >= barrier
    else:
        touched = spots <= barrier
    if inout == InOut.OUT:
        v = np.where(touched, rebate, terminal)
    else:
        v = np.where(touched, terminal, rebate)

    disc = np.exp(-r * dt)
    for _ in range(n_steps - 1, -1, -1):
        T = _transition_matrix(ln_s, dt, r, q, vol)
        v = disc * (T.T @ v)
        spots = np.exp(ln_s)
        if updown == UpDown.UP:
            touched = spots >= barrier
        else:
            touched = spots <= barrier
        # rebate 为触碰时点即期支付 (已在本步 continuation 贴现之外写入, 避免双重贴现)
        if inout == InOut.OUT:
            v = np.where(touched, rebate, v)
        else:
            v = np.where(~touched, rebate, v)

    # 初始 spot 处的价值 (插值)
    ln_spot = np.log(s)
    return float(np.interp(ln_spot, ln_s, v))


def airbag_quad(
    *,
    s: float,
    strike: float,
    barrier: float,
    knockin_parti: float,
    call_parti: float,
    reset_call_parti: float,
    r: float,
    q: float,
    vol: float,
    t: float,
    n_steps: int = 252,
    n_points: int = 401,
) -> float:
    """气囊数值积分 (障碍腿分解)。"""
    cdo = barrier_quad(
        s=s, strike=strike, barrier=barrier, rebate=0.0,
        updown=UpDown.DOWN, inout=InOut.OUT, callput=CallPut.CALL,
        r=r, q=q, vol=vol, t=t, n_steps=n_steps, n_points=n_points,
    )
    cdi = barrier_quad(
        s=s, strike=strike, barrier=barrier, rebate=0.0,
        updown=UpDown.DOWN, inout=InOut.IN, callput=CallPut.CALL,
        r=r, q=q, vol=vol, t=t, n_steps=n_steps, n_points=n_points,
    )
    pdi = barrier_quad(
        s=s, strike=strike, barrier=barrier, rebate=0.0,
        updown=UpDown.DOWN, inout=InOut.IN, callput=CallPut.PUT,
        r=r, q=q, vol=vol, t=t, n_steps=n_steps, n_points=n_points,
    )
    return float(call_parti * cdo + reset_call_parti * cdi - knockin_parti * pdi)
