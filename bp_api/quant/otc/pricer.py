"""顶层定价编排: 由请求字典构建产品 → 运行引擎 → 计算 Greeks → 现状判定 → 示意图数据。"""

from __future__ import annotations

import copy
import math
from dataclasses import dataclass, field
from datetime import date, timedelta
from typing import Any, Optional

import numpy as np
import pandas as pd

from . import engine as eng
from .calendar import (
    TradingCalendarView,
    gen_ko_observation_dates,
    year_fraction,
)
from .enums import (
    CallPut,
    DayCount,
    DealStatus,
    Direction,
    EngineType,
    InOut,
    ProductType,
    UpDown,
    sign_of,
)


@dataclass
class PriceResult:
    price: float
    present_notional: float
    status: str
    greeks: dict[str, float]
    chart: dict[str, Any]
    meta: dict[str, Any] = field(default_factory=dict)
    current_pnl: Optional[float] = None

    def to_dict(self) -> dict:
        d = {
            "price": self.price,
            "present_notional": self.present_notional,
            "status": self.status,
            "greeks": self.greeks,
            "chart": self.chart,
            "meta": self.meta,
        }
        if self.current_pnl is not None:
            d["current_pnl"] = self.current_pnl
        return d


def _f(spec: dict, key: str, default=None):
    v = spec.get(key, default)
    return default if v is None else v


def _parse_date(v) -> date:
    if isinstance(v, date):
        return v
    return date.fromisoformat(str(v)[:10])


def _df(
    r: float,
    day_count: DayCount | str,
    d0: date,
    d1: date,
    cal: TradingCalendarView,
) -> float:
    """现金流贴现因子: 使用所选 day_count 年化 (与票息应计口径一致)。

    GBM 路径仍用交易日网格 (business_offset / t_step); 扩散时钟与 DF 刻度可不同。
    """
    if d1 <= d0:
        return 1.0
    return float(math.exp(-r * year_fraction(day_count, d0, d1, cal)))


def _effective_start(start: date, cal: TradingCalendarView) -> date:
    return cal.roll(start, "following") or start


def _auto_s0(spec: dict, market: Optional[pd.Series], eff_start: date) -> float:
    """起始日(递延后)真实收盘价; 无行情则回退入参 s0。"""
    if market is not None and not market.empty:
        sub = market[market.index.date <= eff_start]
        if not sub.empty:
            return float(sub.iloc[-1])
    return float(spec["s0"])


# ---------------------------------------------------------------------------
# 单次定价 (给定估值日/spot/vol/r), 供 base + Greeks 复用
# ---------------------------------------------------------------------------
def _price_once(
    spec: dict,
    cal: TradingCalendarView,
    *,
    spot: float,
    r: float,
    vol: float,
    q: float,
    valuation: date,
    seed: int,
    return_paths: bool = False,
):
    product = ProductType(spec["product_type"])
    engine = EngineType(spec.get("engine", "mc"))
    s0 = float(spec["s0"])
    notional = float(spec["notional"])
    maturity = _parse_date(spec["maturity_date"])
    start = _parse_date(spec["start_date"])
    day_count = DayCount(spec.get("day_count", "ACT365"))
    t_step = int(spec.get("t_step_per_year", 252))
    n_paths = int(spec.get("n_paths", 100_000))
    dt = 1.0 / t_step

    if valuation >= maturity:
        # 已到期: 返回 0 时间价值(内在价值在 status/chart 中另行处理)
        empty = np.full((1, 1), spot)
        return (0.0, empty) if return_paths else 0.0

    n_steps = cal.business_offset(valuation, maturity)
    if n_steps <= 0:
        return (0.0, None) if return_paths else 0.0
    # 扩散用交易日时钟; 现金流 DF 用 day_count (见 _df)
    t_year = n_steps / t_step
    mat_discount = _df(r, day_count, valuation, maturity, cal)
    sgn = sign_of(spec.get("direction", "buy"))

    def _lvl(pct) -> float:
        return s0 * float(pct) / 100.0

    # ---- 解析解/积分法 (障碍/气囊) ----
    if engine in (EngineType.ANALYTIC, EngineType.QUAD) and product in (ProductType.BARRIER, ProductType.AIRBAG):
        if product == ProductType.BARRIER:
            if engine == EngineType.QUAD:
                pv_unit = eng.barrier_quad(
                    s=spot, strike=_lvl(_f(spec, "strike_pct", 100)),
                    barrier=_lvl(_f(spec, "barrier_pct", 110)), rebate=float(_f(spec, "rebate", 0.0)),
                    updown=UpDown(spec.get("updown", "up")), inout=InOut(spec.get("inout", "out")),
                    callput=CallPut(spec.get("callput", "call")), r=r, q=q, vol=vol, t=t_year,
                )
            else:
                pv_unit = eng.barrier_analytic(
                    s=spot, strike=_lvl(_f(spec, "strike_pct", 100)),
                    barrier=_lvl(_f(spec, "barrier_pct", 110)), rebate=float(_f(spec, "rebate", 0.0)),
                    updown=UpDown(spec.get("updown", "up")), inout=InOut(spec.get("inout", "out")),
                    callput=CallPut(spec.get("callput", "call")), r=r, q=q, vol=vol, t=t_year,
                )
            pv = sgn * float(_f(spec, "parti", 1.0)) * pv_unit / s0 * notional
        else:
            if engine == EngineType.QUAD:
                pv_unit = eng.airbag_quad(
                    s=spot, strike=_lvl(_f(spec, "strike_pct", 100)),
                    barrier=_lvl(_f(spec, "barrier_pct", 70)),
                    knockin_parti=float(_f(spec, "knockin_parti", 1.0)),
                    call_parti=float(_f(spec, "call_parti", 1.0)),
                    reset_call_parti=float(_f(spec, "reset_call_parti", 1.0)),
                    r=r, q=q, vol=vol, t=t_year,
                )
            else:
                pv_unit = eng.airbag_analytic(
                    s=spot, strike=_lvl(_f(spec, "strike_pct", 100)),
                    barrier=_lvl(_f(spec, "barrier_pct", 70)),
                    knockin_parti=float(_f(spec, "knockin_parti", 1.0)),
                    call_parti=float(_f(spec, "call_parti", 1.0)),
                    reset_call_parti=float(_f(spec, "reset_call_parti", 1.0)),
                    r=r, q=q, vol=vol, t=t_year,
                )
            pv = sgn * pv_unit / s0 * notional
        if return_paths:
            steps = np.arange(n_steps + 1)
            fwd = spot * np.exp((r - q) * steps * dt)
            return pv, fwd
        return pv

    # ---- 蒙特卡洛 (分批, 内存受控) ----
    if product == ProductType.SNOWBALL:
        ko_future = [d for d in _resolve_ko_dates(spec, cal, start, maturity) if d > valuation]
        ko_idx = np.array([cal.business_offset(valuation, d) for d in ko_future], dtype=int)
        coupon_out = float(_f(spec, "coupon_out", 0.0))
        coupon_div = float(_f(spec, "coupon_div", coupon_out))
        ko_amounts = np.array([coupon_out * year_fraction(day_count, start, d, cal) * notional for d in ko_future])
        ko_discounts = np.array([_df(r, day_count, valuation, d, cal) for d in ko_future])
        maturity_div_amount = coupon_div * year_fraction(day_count, start, maturity, cal) * notional
        ko_barrier = _lvl(_f(spec, "ko_barrier_pct", 103))
        ki_barrier = _lvl(_f(spec, "ki_barrier_pct", 75))
        ki_strike = _lvl(_f(spec, "ki_strike_pct", 80))
        already = bool(spec.get("already_ki", False))

        def payoff_fn(paths):
            return eng.snowball_payoff(
                paths, ko_obs_idx=ko_idx, ko_barrier=ko_barrier, ko_coupon_amounts=ko_amounts,
                ko_discounts=ko_discounts, ki_barrier=ki_barrier, ki_strike=ki_strike, s0=s0,
                notional=notional, maturity_div_amount=maturity_div_amount,
                maturity_discount=mat_discount, already_ki=already,
            )

    elif product == ProductType.PHOENIX:
        ko_future = [d for d in _resolve_ko_dates(spec, cal, start, maturity) if d > valuation]
        obs_idx = np.array([cal.business_offset(valuation, d) for d in ko_future], dtype=int)
        period_coupon = float(_f(spec, "period_coupon", 0.0)) * notional
        discounts = np.array([_df(r, day_count, valuation, d, cal) for d in ko_future])
        ko_barrier = _lvl(_f(spec, "ko_barrier_pct", 103))
        coupon_barrier = _lvl(_f(spec, "coupon_barrier_pct", _f(spec, "ki_barrier_pct", 75)))
        ki_barrier = _lvl(_f(spec, "ki_barrier_pct", 75))
        ki_strike = _lvl(_f(spec, "ki_strike_pct", 80))
        already = bool(spec.get("already_ki", False))

        def payoff_fn(paths):
            return eng.phoenix_payoff(
                paths, obs_idx=obs_idx, ko_barrier=ko_barrier, coupon_barrier=coupon_barrier,
                period_coupon_amount=period_coupon, period_discounts=discounts, ki_barrier=ki_barrier,
                ki_strike=ki_strike, s0=s0, notional=notional, maturity_discount=mat_discount,
                already_ki=already,
            )

    elif product == ProductType.AIRBAG:
        strike = _lvl(_f(spec, "strike_pct", 100))
        barrier = _lvl(_f(spec, "barrier_pct", 70))
        kip = float(_f(spec, "knockin_parti", 1.0))
        cp = float(_f(spec, "call_parti", 1.0))
        rcp = float(_f(spec, "reset_call_parti", 1.0))
        discrete = bool(spec.get("discrete_obs", True))

        def payoff_fn(paths):
            return eng.airbag_payoff(
                paths, strike=strike, barrier=barrier, knockin_parti=kip, call_parti=cp,
                reset_call_parti=rcp, s0=s0, notional=notional, discount=mat_discount, discrete=discrete,
            )

    else:  # BARRIER
        strike = _lvl(_f(spec, "strike_pct", 100))
        barrier = _lvl(_f(spec, "barrier_pct", 110))
        parti = float(_f(spec, "parti", 1.0))
        # rebate 与 analytic(parti * 含 rebate 的单位价)对齐: 也乘 parti
        rebate_amt = float(_f(spec, "rebate", 0.0)) / s0 * notional * parti
        updown = UpDown(spec.get("updown", "up"))
        inout = InOut(spec.get("inout", "out"))
        callput = CallPut(spec.get("callput", "call"))
        discrete = bool(spec.get("discrete_obs", True))

        def payoff_fn(paths):
            return eng.barrier_payoff(
                paths, strike=strike, barrier=barrier, rebate=rebate_amt, parti=parti, updown=updown,
                inout=inout, callput=callput, s0=s0, notional=notional, discount=mat_discount,
                discrete=discrete,
            )

    batch = int(spec.get("mc_batch", 20000))
    mean_pv, mean_path = eng.mc_expectation(
        spot=spot, r=r, q=q, vol=vol, n_steps=n_steps, dt=dt, n_paths=n_paths,
        payoff_fn=payoff_fn, seed=seed, batch=batch, want_mean_path=return_paths,
    )
    pv = sgn * mean_pv
    if return_paths:
        return pv, mean_path
    return pv


def _resolve_ko_dates(spec: dict, cal: TradingCalendarView, start: date, maturity: date) -> list[date]:
    explicit = spec.get("ko_observation_dates")
    lock = int(spec.get("lock_term_months", 0))
    if explicit:
        lock_end = start
        if lock > 0:
            from .calendar import _add_months
            lock_end = _add_months(start, lock)
        dates = []
        seen = set()
        for v in explicit:
            d = _parse_date(v)
            if d <= lock_end:
                continue
            rd = cal.roll(d, "following")
            if rd and rd not in seen and rd <= maturity:
                seen.add(rd)
                dates.append(rd)
        mat = cal.roll(maturity, "following") or maturity
        if mat not in seen:
            dates.append(mat)
        dates.sort()
        return dates
    return gen_ko_observation_dates(
        start, maturity, cal,
        freq_months=int(spec.get("ko_freq_months", 1)),
        lock_term_months=lock,
    )


# ---------------------------------------------------------------------------
# Greeks (bump-and-reprice + 公共随机数)
# ---------------------------------------------------------------------------
def _compute_greeks(spec, cal, *, spot, r, vol, q, valuation, seed, base_pv) -> dict[str, float]:
    h = max(spot * 0.01, 1e-6)
    dv = 0.01
    dr = 1e-4

    def P(**kw):
        return _price_once(spec, cal, spot=kw.get("spot", spot), r=kw.get("r", r),
                           vol=kw.get("vol", vol), q=q, valuation=kw.get("valuation", valuation), seed=seed)

    p_up = P(spot=spot + h)
    p_dn = P(spot=spot - h)
    delta = (p_up - p_dn) / (2 * h)
    gamma = (p_up - 2 * base_pv + p_dn) / (h * h)

    v_up = P(vol=vol + dv)
    v_dn = P(vol=max(vol - dv, 1e-4))
    vega = (v_up - v_dn) / 2.0            # 每 1 个百分点(0.01)波动率

    r_up = P(r=r + dr)
    r_dn = P(r=r - dr)
    rho = (r_up - r_dn) / (2 * dr) * 0.01  # 每 1 个百分点无风险利率

    # theta: 估值日前进一个交易日 (spot 不变), 每日时间价值损耗
    nxt = cal.next_trading_day(valuation, inclusive=False)
    if nxt is not None and nxt < _parse_date(spec["maturity_date"]):
        days = max((nxt - valuation).days, 1)
        p_next = P(valuation=nxt)
        theta = (p_next - base_pv) / days   # 每自然日
    else:
        theta = 0.0

    return {
        "delta": float(delta),
        "gamma": float(gamma),
        "vega": float(vega),
        "theta": float(theta),
        "rho": float(rho),
    }


# ---------------------------------------------------------------------------
# 现状判定 + 示意图
# ---------------------------------------------------------------------------
def _rebased_series(market: Optional[pd.Series], start: date, s0: float) -> Optional[pd.Series]:
    if market is None or market.empty:
        return None
    m = market.dropna()
    if m.empty:
        return None
    base_idx = m.index[m.index <= pd.Timestamp(start)]
    base = m.loc[base_idx[-1]] if len(base_idx) else m.iloc[0]
    if base == 0:
        return None
    return m / float(base) * s0


def _level_on_date(rebased: Optional[pd.Series], d: date) -> Optional[float]:
    """事件日挂钩指数(重基准后)收盘。"""
    if rebased is None or rebased.empty:
        return None
    ts = pd.Timestamp(d)
    if ts in rebased.index:
        return float(rebased.loc[ts])
    sub = rebased[rebased.index.date == d]
    if not sub.empty:
        return float(sub.iloc[-1])
    prior = rebased[rebased.index <= ts]
    if not prior.empty:
        return float(prior.iloc[-1])
    return None


def _spot_raw(market: Optional[pd.Series], vd: date, fallback: float) -> float:
    if market is None or market.empty:
        return fallback
    sub = market[market.index.date <= vd]
    if sub.empty:
        return fallback
    return float(sub.iloc[-1])


def _detect_status(
    spec, cal, s0, start, maturity, valuation, rebased: Optional[pd.Series]
) -> tuple[str, list[dict], Optional[float], Optional[date], Optional[date]]:
    """返回 (status, events, spot_val, ko_event_date, first_ki_date)。"""
    events: list[dict] = []
    product = ProductType(spec["product_type"])
    spot_val: Optional[float] = None
    ko_line = s0 * float(_f(spec, "ko_barrier_pct", 103)) / 100.0
    ki_line = s0 * float(_f(spec, "ki_barrier_pct", 75)) / 100.0
    ko_event_date: Optional[date] = None
    first_ki_date: Optional[date] = None

    status = DealStatus.ALIVE
    if bool(spec.get("already_ki", False)):
        status = DealStatus.KNOCKED_IN

    lock = int(spec.get("lock_term_months", 0))
    lock_end = start
    if lock > 0:
        from .calendar import _add_months
        lock_end = _add_months(start, lock)

    if rebased is not None:
        hist = rebased[(rebased.index >= pd.Timestamp(start)) & (rebased.index <= pd.Timestamp(valuation))]
        if not hist.empty:
            spot_val = float(hist.iloc[-1])
            if product in (ProductType.SNOWBALL, ProductType.PHOENIX):
                ko_dates = _resolve_ko_dates(spec, cal, start, maturity)
                # 1) 先判定敲出 (锁定期后、<= 估值日的观察日)
                for od in ko_dates:
                    if od > valuation:
                        break
                    if od <= lock_end:
                        continue
                    lvl = _level_on_date(rebased, od)
                    if lvl is not None and lvl >= ko_line:
                        status = DealStatus.KNOCKED_OUT
                        ko_event_date = od
                        events.append({
                            "type": "knock_out",
                            "date": od.isoformat(),
                            "level": round(lvl, 4),
                            "terminated": True,
                        })
                        break
                # 2) 敲入仅在敲出之前 (或无敲出则 <= 估值日)
                ki_cutoff = ko_event_date if ko_event_date else valuation
                below = hist[(hist.index <= pd.Timestamp(ki_cutoff)) & (hist < ki_line)]
                if not below.empty and status != DealStatus.KNOCKED_OUT:
                    status = DealStatus.KNOCKED_IN
                    spec["already_ki"] = True
                    d0 = below.index[0].date()
                    first_ki_date = d0
                    events.insert(0, {
                        "type": "knock_in",
                        "date": d0.isoformat(),
                        "level": round(float(below.iloc[0]), 4),
                    })
                elif not below.empty and ko_event_date and below.index[0].date() < ko_event_date:
                    # 敲出前曾敲入 — 记录事件但不改 status (已敲出优先)
                    d0 = below.index[0].date()
                    first_ki_date = d0
                    if not any(e.get("type") == "knock_in" for e in events):
                        events.insert(0, {
                            "type": "knock_in",
                            "date": d0.isoformat(),
                            "level": round(float(below.iloc[0]), 4),
                        })

    if valuation >= maturity and status != DealStatus.KNOCKED_OUT:
        status = DealStatus.EXPIRED
    return status.value, events, spot_val, ko_event_date, first_ki_date


def _phoenix_accrued_coupons_pv(
    spec: dict,
    cal: TradingCalendarView,
    rebased: Optional[pd.Series],
    s0: float,
    *,
    end_date: date,
    asof: date,
) -> float:
    """凤凰已派期间票息现值 (asof 视角); 观察日点位 >= 派息障碍则计入。"""
    start = _parse_date(spec["start_date"])
    maturity = _parse_date(spec["maturity_date"])
    day_count = DayCount(spec.get("day_count", "ACT365"))
    notional = float(spec["notional"])
    r = float(spec["r"])
    period = float(_f(spec, "period_coupon", 0.0)) * notional
    coupon_line = s0 * float(_f(spec, "coupon_barrier_pct", _f(spec, "ki_barrier_pct", 75))) / 100.0
    total = 0.0
    for od in _resolve_ko_dates(spec, cal, start, maturity):
        if od > end_date:
            break
        lvl = _level_on_date(rebased, od)
        if lvl is None:
            continue
        if lvl >= coupon_line:
            total += period * _df(r, day_count, asof, od, cal)
    return total


def _knocked_out_pv(
    spec: dict,
    cal: TradingCalendarView,
    s0: float,
    ko_date: date,
    *,
    rebased: Optional[pd.Series] = None,
) -> float:
    """已敲出终止: 锁定票息现值 (雪球敲出票息 / 凤凰累计期间派息)。"""
    product = ProductType(spec["product_type"])
    start = _parse_date(spec["start_date"])
    day_count = DayCount(spec.get("day_count", "ACT365"))
    notional = float(spec["notional"])
    r = float(spec["r"])
    sgn = sign_of(spec.get("direction", "buy"))
    if product == ProductType.PHOENIX:
        # 与 phoenix_payoff 一致: 观察日先派息再判定敲出; DF 相对起始日(与雪球锁定口径一致)
        return sgn * _phoenix_accrued_coupons_pv(
            spec, cal, rebased, s0, end_date=ko_date, asof=start,
        )
    coupon_out = float(_f(spec, "coupon_out", 0.0))
    yf = year_fraction(day_count, start, ko_date, cal)
    return sgn * coupon_out * notional * yf * _df(r, day_count, start, ko_date, cal)


def _airbag_barrier_maturity_pv(
    spec: dict,
    market: Optional[pd.Series],
    s0: float,
    maturity: date,
) -> float:
    """气囊/障碍到期内在价值: 复用 payoff (discount=1)。"""
    product = ProductType(spec["product_type"])
    notional = float(spec["notional"])
    sgn = sign_of(spec.get("direction", "buy"))
    final_spot = _spot_raw(market, maturity, s0)
    # 单路径: [估值占位, 到期]; discrete 监控用 paths[:,1:]
    paths = np.array([[final_spot, final_spot]], dtype=float)

    def _lvl(pct) -> float:
        return s0 * float(pct) / 100.0

    if product == ProductType.AIRBAG:
        pay = eng.airbag_payoff(
            paths,
            strike=_lvl(_f(spec, "strike_pct", 100)),
            barrier=_lvl(_f(spec, "barrier_pct", 70)),
            knockin_parti=float(_f(spec, "knockin_parti", 1.0)),
            call_parti=float(_f(spec, "call_parti", 1.0)),
            reset_call_parti=float(_f(spec, "reset_call_parti", 1.0)),
            s0=s0,
            notional=notional,
            discount=1.0,
            discrete=bool(spec.get("discrete_obs", True)),
        )
    else:
        parti = float(_f(spec, "parti", 1.0))
        rebate_amt = float(_f(spec, "rebate", 0.0)) / s0 * notional * parti
        pay = eng.barrier_payoff(
            paths,
            strike=_lvl(_f(spec, "strike_pct", 100)),
            barrier=_lvl(_f(spec, "barrier_pct", 110)),
            rebate=rebate_amt,
            parti=parti,
            updown=UpDown(spec.get("updown", "up")),
            inout=InOut(spec.get("inout", "out")),
            callput=CallPut(spec.get("callput", "call")),
            s0=s0,
            notional=notional,
            discount=1.0,
            discrete=bool(spec.get("discrete_obs", True)),
        )
    return sgn * float(pay[0])


def _maturity_settlement_pv(
    spec: dict,
    cal: TradingCalendarView,
    market: Optional[pd.Series],
    s0: float,
    maturity: date,
    *,
    already_ki: bool,
    rebased: Optional[pd.Series] = None,
) -> float:
    """到期结算价值 (非 MC, 已实现 payoff)。"""
    product = ProductType(spec["product_type"])
    if product in (ProductType.AIRBAG, ProductType.BARRIER):
        return _airbag_barrier_maturity_pv(spec, market, s0, maturity)

    start = _parse_date(spec["start_date"])
    day_count = DayCount(spec.get("day_count", "ACT365"))
    notional = float(spec["notional"])
    r = float(spec["r"])
    sgn = sign_of(spec.get("direction", "buy"))
    final_spot = _spot_raw(market, maturity, s0)
    ki_strike = s0 * float(_f(spec, "ki_strike_pct", 80)) / 100.0

    if product == ProductType.PHOENIX:
        coupons = _phoenix_accrued_coupons_pv(
            spec, cal, rebased, s0, end_date=maturity, asof=start,
        )
        if already_ki:
            loss = max(ki_strike - final_spot, 0.0) / s0 * notional
            return sgn * coupons - sgn * loss
        return sgn * coupons

    if already_ki:
        loss = max(ki_strike - final_spot, 0.0) / s0 * notional
        return -sgn * loss
    coupon_div = float(_f(spec, "coupon_div", _f(spec, "coupon_out", 0.0)))
    yf = year_fraction(day_count, start, maturity, cal)
    return sgn * coupon_div * notional * yf * _df(r, day_count, start, maturity, cal)


def _lifecycle_pv(
    spec: dict,
    cal: TradingCalendarView,
    market: Optional[pd.Series],
    vd: date,
    *,
    s0: float,
    eff_start: date,
    maturity: date,
    ko_event_date: Optional[date],
    first_ki_date: Optional[date],
) -> float:
    """生命周期感知价值: 敲出锁定票息 / 到期结算 / 存续 MC。"""
    rebased = _rebased_series(market, eff_start, s0)
    if ko_event_date is not None and vd >= ko_event_date:
        return _knocked_out_pv(spec, cal, s0, ko_event_date, rebased=rebased)
    if vd >= maturity:
        already_ki = first_ki_date is not None and first_ki_date <= maturity
        return _maturity_settlement_pv(
            spec, cal, market, s0, maturity,
            already_ki=already_ki or bool(spec.get("already_ki")),
            rebased=rebased,
        )
    sub = copy.deepcopy(spec)
    sub["valuation_date"] = vd.isoformat()
    already_ki = (first_ki_date is not None and first_ki_date <= vd) or bool(spec.get("already_ki"))
    sub["already_ki"] = already_ki
    spot = _spot_raw(market, vd, s0)
    sub["spot"] = spot
    pnl_paths = min(int(spec.get("n_paths", 100_000)), int(spec.get("pnl_paths", 20_000)))
    pnl_paths = max(pnl_paths, 5_000)
    sub["n_paths"] = pnl_paths
    sub["greeks"] = False
    return _price_once(
        sub, cal, spot=spot, r=float(spec["r"]), vol=float(spec["vol"]),
        q=float(spec["q"]), valuation=vd, seed=int(spec.get("seed", 42)),
    )


def _downsample_dates(cal: TradingCalendarView, start: date, end: date, target: int = 50) -> list[date]:
    days = cal.sessions_in(start, end, include_start=True, include_end=True)
    if len(days) <= target:
        return days
    step = max(len(days) // target, 1)
    sampled = days[::step]
    if sampled[-1] != days[-1]:
        sampled.append(days[-1])
    return sampled


def _force_pnl_last(aligned: list[Optional[float]], value: float) -> list[Optional[float]]:
    """保证示意图末日盈亏 == 结果卡 current_pnl。"""
    if not aligned:
        return [value]
    out = list(aligned)
    out[-1] = value
    return out


def _compute_pnl_series(
    spec: dict,
    cal: TradingCalendarView,
    market: Optional[pd.Series],
    *,
    start: date,
    s0: float,
    eff_start: date,
    maturity: date,
    chart_dates: list[date],
    ko_event_date: Optional[date],
    first_ki_date: Optional[date],
    chart_end: Optional[date] = None,
) -> tuple[list[Optional[float]], float, float]:
    """降采样逐日盯市 盈亏(t) = round(生命周期价值(t) - 价值(期初), 2)。

    current_pnl 与图表末日对齐到同一交易日 trading_end, 并强制 aligned[-1] == current_pnl。
    """
    valuation = _parse_date(spec.get("valuation_date") or start)
    end = chart_end or min(valuation, maturity)
    trading_end = cal.prev_trading_day(end, inclusive=True) or end
    sample = _downsample_dates(cal, start, end, target=50)
    for extra in (trading_end, ko_event_date):
        if extra is not None and extra not in sample:
            sample.append(extra)
    if cal.is_trading_day(valuation) and valuation not in sample and valuation <= end:
        sample.append(valuation)
    sample.sort()

    pv_start = _lifecycle_pv(
        spec, cal, market, start, s0=s0, eff_start=eff_start, maturity=maturity,
        ko_event_date=ko_event_date, first_ki_date=first_ki_date,
    )

    pnl_map: dict[str, float] = {}
    for vd in sample:
        pv_t = _lifecycle_pv(
            spec, cal, market, vd, s0=s0, eff_start=eff_start, maturity=maturity,
            ko_event_date=ko_event_date, first_ki_date=first_ki_date,
        )
        pnl_map[vd.isoformat()] = round(pv_t - pv_start, 2)

    pv_end = _lifecycle_pv(
        spec, cal, market, trading_end, s0=s0, eff_start=eff_start, maturity=maturity,
        ko_event_date=ko_event_date, first_ki_date=first_ki_date,
    )
    current_pnl = round(pv_end - pv_start, 2)
    pnl_map[trading_end.isoformat()] = current_pnl

    aligned = [pnl_map.get(d.isoformat()) for d in chart_dates]
    aligned = _force_pnl_last(aligned, current_pnl)
    return aligned, pv_start, current_pnl


def _build_chart(spec, cal, s0, start, maturity, valuation, rebased, status, events, forward_mean,
                 pnl=None, pnl_start=0.0, chart_end: Optional[date] = None):
    """示意图仅覆盖 [start, chart_end], 默认截断到估值日 — 不注入未来均值。"""
    end = chart_end if chart_end is not None else min(valuation, maturity)
    all_days = cal.sessions_in(start, end, include_start=True, include_end=True)
    if not all_days:
        all_days = [start]
    dates = [d.isoformat() for d in all_days]
    date_set = set(dates)
    underlying: list[Optional[float]] = []
    realized_map: dict[date, float] = {}
    if rebased is not None:
        for ts, val in rebased.items():
            if ts.date() <= end:
                realized_map[ts.date()] = float(val)
    for d in all_days:
        if d in realized_map:
            underlying.append(round(realized_map[d], 4))
        else:
            underlying.append(None)

    lock = int(spec.get("lock_term_months", 0))
    lock_area = None
    lock_end_iso: Optional[str] = None
    if lock > 0:
        from .calendar import _add_months
        le = cal.roll(_add_months(start, lock), "following") or _add_months(start, lock)
        le_clip = min(le, end)
        lock_area = [start.isoformat(), le_clip.isoformat()]
        lock_end_iso = le.isoformat()
    else:
        lock_end_iso = start.isoformat()

    # 仅保留落在图表日期内的事件; 敲出至多 1 个且须 terminated
    chart_events: list[dict] = []
    ko_seen = False
    for e in (events or []):
        if e.get("date") not in date_set:
            continue
        if e.get("type") == "knock_out":
            if ko_seen:
                continue
            ko_seen = True
            e = {**e, "terminated": True}
        chart_events.append(e)

    product = ProductType(spec["product_type"])
    ko_obs_iso: list[str] = []
    if product in (ProductType.SNOWBALL, ProductType.PHOENIX):
        for od in _resolve_ko_dates(spec, cal, start, maturity):
            if start <= od <= end:
                ko_obs_iso.append(od.isoformat())

    baseline = [round(s0, 4)] * len(all_days)
    # forward_mean / mean_path 已废弃: 示意图不展示 MC 预测, 保留空数组兼容前端
    _ = forward_mean
    _ = status

    return {
        "dates": dates,
        "underlying": underlying,
        "forward_mean": [],
        "mean_path": [],
        "ko_line": round(s0 * float(_f(spec, "ko_barrier_pct", 103)) / 100.0, 4)
        if product in (ProductType.SNOWBALL, ProductType.PHOENIX) else None,
        "ki_line": round(s0 * float(_f(spec, "ki_barrier_pct", 75)) / 100.0, 4)
        if product in (ProductType.SNOWBALL, ProductType.PHOENIX) else None,
        "baseline_line": baseline,
        "lock_area": lock_area,
        "lock_end": lock_end_iso,
        "ko_observation_dates": ko_obs_iso,
        "events": chart_events,
        "s0": s0,
        "valuation_date": valuation.isoformat(),
        "pnl": pnl,
        "pnl_start": pnl_start,
    }


# ---------------------------------------------------------------------------
# 对外入口
# ---------------------------------------------------------------------------
def price_deal(
    spec: dict,
    cal: TradingCalendarView,
    market: Optional[pd.Series] = None,
    progress_cb=None,
) -> PriceResult:
    """定价 + Greeks + 现状 + 示意图。spec 为已校验的参数字典。"""
    start = _parse_date(spec["start_date"])
    maturity = _parse_date(spec["maturity_date"])
    valuation = _parse_date(spec.get("valuation_date") or spec["start_date"])
    eff_start = _effective_start(start, cal)
    s0 = _auto_s0(spec, market, eff_start)
    spec = copy.deepcopy(spec)
    spec["s0"] = s0
    r = float(spec["r"])
    q = float(spec["q"])
    vol = float(spec["vol"])
    seed = int(spec.get("seed", 42))
    compute_pnl = bool(spec.get("compute_pnl", True))

    rebased = _rebased_series(market, eff_start, s0)

    spot = spec.get("spot")
    if spot is None:
        if rebased is not None:
            hist = rebased[rebased.index <= pd.Timestamp(valuation)]
            spot = float(hist.iloc[-1]) if not hist.empty else s0
        else:
            spot = s0
    spot = float(spot)

    def report(cur, total, msg):
        if progress_cb:
            try:
                progress_cb(cur, total, msg)
            except Exception:  # noqa: BLE001
                pass

    report(1, 7, "存续判定")
    status, events, _spot_val, ko_event_date, first_ki_date = _detect_status(
        spec, cal, s0, eff_start, maturity, valuation, rebased
    )

    if status == DealStatus.KNOCKED_OUT.value and ko_event_date is not None:
        locked_coupon = _knocked_out_pv(spec, cal, s0, ko_event_date, rebased=rebased)
        chart_end = ko_event_date
        chart_days = cal.sessions_in(eff_start, chart_end, include_start=True, include_end=True) or [eff_start]
        # 结果卡口径: 已实现敲出票息; 示意图末日强制同值
        current_pnl = round(locked_coupon, 2)
        pnl, pv_start = None, 0.0
        if compute_pnl:
            pnl, pv_start, _ = _compute_pnl_series(
                spec, cal, market, start=eff_start, s0=s0, eff_start=eff_start,
                maturity=maturity, chart_dates=chart_days,
                ko_event_date=ko_event_date, first_ki_date=first_ki_date,
                chart_end=chart_end,
            )
            pnl = _force_pnl_last(pnl or [], current_pnl)
        chart = _build_chart(
            spec, cal, s0, eff_start, maturity, valuation, rebased, status, events, None,
            pnl=pnl, pnl_start=pv_start, chart_end=chart_end,
        )
        report(7, 7, "完成(已敲出)")
        return PriceResult(
            price=0.0,
            present_notional=0.0,
            status=status,
            greeks={},
            chart=chart,
            current_pnl=current_pnl,
            meta={
                "engine": spec.get("engine", "mc"),
                "product_type": spec["product_type"],
                "spot": round(spot, 4),
                "valuation_date": valuation.isoformat(),
                "terminated": True,
                "ko_date": ko_event_date.isoformat(),
                "realized_profit": round(locked_coupon, 2),
            },
        )

    report(2, 7, "基准定价")
    base_pv = _price_once(spec, cal, spot=spot, r=r, vol=vol, q=q,
                          valuation=valuation, seed=seed, return_paths=False)

    report(3, 7, "计算 Delta/Gamma")
    want_greeks = bool(spec.get("greeks", True))
    if want_greeks:
        greeks = _compute_greeks(spec, cal, spot=spot, r=r, vol=vol, q=q,
                                 valuation=valuation, seed=seed, base_pv=base_pv)
    else:
        greeks = {}

    # 示意图 / 盈亏仅截至估值日, 杜绝未来函数
    chart_end = min(valuation, maturity)
    chart_days = cal.sessions_in(eff_start, chart_end, include_start=True, include_end=True) or [eff_start]
    pnl, pnl_start, current_pnl = None, 0.0, None
    if compute_pnl:
        report(5, 7, "浮动盈亏序列")
        pnl, pnl_start, current_pnl = _compute_pnl_series(
            spec, cal, market, start=eff_start, s0=s0, eff_start=eff_start,
            maturity=maturity, chart_dates=chart_days,
            ko_event_date=ko_event_date, first_ki_date=first_ki_date,
            chart_end=chart_end,
        )

    report(6, 7, "示意图")
    chart = _build_chart(
        spec, cal, s0, eff_start, maturity, valuation, rebased, status, events, None,
        pnl=pnl, pnl_start=pnl_start, chart_end=chart_end,
    )

    present_notional = 0.0 if status == DealStatus.KNOCKED_OUT.value else float(spec["notional"])
    report(7, 7, "完成")

    return PriceResult(
        price=round(float(base_pv), 4),
        present_notional=present_notional,
        status=status,
        greeks={k: round(v, 6) for k, v in greeks.items()},
        chart=chart,
        current_pnl=round(current_pnl, 2) if current_pnl is not None else None,
        meta={
            "engine": spec.get("engine", "mc"),
            "product_type": spec["product_type"],
            "spot": round(spot, 4),
            "valuation_date": valuation.isoformat(),
            "n_paths": int(spec.get("n_paths", 100_000)),
            "s0": round(s0, 4),
        },
    )
