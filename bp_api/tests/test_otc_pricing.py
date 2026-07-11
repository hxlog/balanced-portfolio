"""场外衍生品定价引擎单测 (纯引擎, 无 DB/网络)。

使用工作日日历(周一至周五)保证确定性; 金标容忍 30% (与外部系统约定)。
"""

from __future__ import annotations

from datetime import date, timedelta

import numpy as np
import pytest

from bp_api.quant.otc import engine as eng
from bp_api.quant.otc.calendar import (
    TradingCalendarView,
    gen_ko_observation_dates,
    year_fraction,
)
from bp_api.quant.otc.enums import CallPut, DayCount, InOut, UpDown
from bp_api.quant.otc.pricer import price_deal


@pytest.fixture(scope="module")
def weekday_cal() -> TradingCalendarView:
    days = []
    d = date(2019, 1, 1)
    end = date(2025, 12, 31)
    while d <= end:
        if d.weekday() < 5:
            days.append(d)
        d += timedelta(days=1)
    return TradingCalendarView(days)


# ---------------------------------------------------------------------------
# 日历 / 计息
# ---------------------------------------------------------------------------
def test_business_offset_and_roll(weekday_cal):
    cal = weekday_cal
    # 2021-03-15 (周一) 是交易日
    assert cal.is_trading_day(date(2021, 3, 15))
    # 2021-05-15 是周六 → following 递延到 05-17 周一
    rolled = cal.roll(date(2021, 5, 15), "following")
    assert rolled == date(2021, 5, 17)
    # 偏移量单调
    off1 = cal.business_offset(date(2021, 3, 15), date(2021, 4, 15))
    off2 = cal.business_offset(date(2021, 3, 15), date(2021, 5, 17))
    assert 0 < off1 < off2


def test_year_fraction():
    assert year_fraction(DayCount.ACT365, date(2021, 3, 15), date(2022, 3, 15)) == pytest.approx(1.0, abs=0.01)
    assert year_fraction(DayCount.ACT360, date(2021, 1, 1), date(2021, 12, 31)) > 1.0


def test_gen_ko_dates_lock(weekday_cal):
    dates = gen_ko_observation_dates(date(2021, 3, 15), date(2022, 3, 15), weekday_cal,
                                     freq_months=1, lock_term_months=3)
    # 锁定 3 个月 → 前 3 个月无敲出观察; 末点为到期
    assert all(d > date(2021, 6, 15) for d in dates)
    assert dates[-1] == date(2022, 3, 15)
    assert all(weekday_cal.is_trading_day(d) for d in dates)


# ---------------------------------------------------------------------------
# 雪球金标
# ---------------------------------------------------------------------------
def _golden_spec() -> dict:
    return {
        "product_type": "snowball", "direction": "buy", "engine": "mc",
        "start_date": "2021-03-15", "maturity_date": "2022-03-15", "valuation_date": "2021-03-15",
        "s0": 100.0, "spot": 100.0,
        "ko_barrier_pct": 103.0, "ki_barrier_pct": 75.0, "ki_strike_pct": 100.0,
        "coupon_out": 0.20, "coupon_div": 0.20,
        "ko_observation_dates": [
            "2021-04-15", "2021-05-17", "2021-06-15", "2021-07-15", "2021-08-16",
            "2021-09-15", "2021-10-15", "2021-11-15", "2021-12-15", "2022-01-17",
            "2022-02-15", "2022-03-15",
        ],
        "lock_term_months": 0, "already_ki": False,
        "r": 0.04, "q": 0.01, "vol": 0.25, "notional": 10_000_000.0,
        "day_count": "ACT365", "t_step_per_year": 252, "n_paths": 80_000, "seed": 7,
        "greeks": False, "compute_pnl": False,
    }


def test_snowball_golden(weekday_cal):
    res = price_deal(_golden_spec(), weekday_cal)
    target = 120193.33
    rel_err = abs(res.price - target) / target
    assert rel_err < 0.30, f"雪球金标偏差过大: {res.price:.2f} vs {target} ({rel_err:.2%})"
    assert res.status in ("alive", "expired", "knocked_in", "knocked_out")
    assert res.present_notional == 10_000_000.0
    assert res.chart["ko_line"] == pytest.approx(103.0)
    assert res.chart["ki_line"] == pytest.approx(75.0)


def test_direction_sign(weekday_cal):
    buy = price_deal({**_golden_spec(), "direction": "buy"}, weekday_cal).price
    sell = price_deal({**_golden_spec(), "direction": "sell"}, weekday_cal).price
    assert sell == pytest.approx(-buy, rel=1e-6)


def test_snowball_coupon_monotonic(weekday_cal):
    lo = price_deal({**_golden_spec(), "coupon_out": 0.10, "coupon_div": 0.10}, weekday_cal).price
    hi = price_deal({**_golden_spec(), "coupon_out": 0.30, "coupon_div": 0.30}, weekday_cal).price
    assert hi > lo


def test_greeks_present(weekday_cal):
    res = price_deal({**_golden_spec(), "greeks": True, "n_paths": 40_000, "compute_pnl": False}, weekday_cal)
    for g in ("delta", "gamma", "vega", "theta", "rho"):
        assert g in res.greeks
        assert np.isfinite(res.greeks[g])


# ---------------------------------------------------------------------------
# 障碍期权解析解: in-out 平价 (cdi + cdo = 普通看涨)
# ---------------------------------------------------------------------------
@pytest.mark.parametrize("updown,callput,barrier", [
    (UpDown.DOWN, CallPut.CALL, 90.0),
    (UpDown.UP, CallPut.CALL, 130.0),
    (UpDown.DOWN, CallPut.PUT, 90.0),
    (UpDown.UP, CallPut.PUT, 130.0),
])
def test_barrier_in_out_parity(updown, callput, barrier):
    kw = dict(s=100.0, strike=100.0, barrier=barrier, rebate=0.0,
              updown=updown, callput=callput, r=0.03, q=0.01, vol=0.2, t=1.0)
    ki = eng.barrier_analytic(inout=InOut.IN, **kw)
    ko = eng.barrier_analytic(inout=InOut.OUT, **kw)
    vanilla = eng.vanilla_bs(s=100.0, strike=100.0, r=0.03, q=0.01, vol=0.2, t=1.0, callput=callput)
    assert ki + ko == pytest.approx(vanilla, rel=1e-3, abs=1e-2)


def test_barrier_mc_matches_analytic_direction(weekday_cal):
    """离散 MC 与连续解析同号且量级接近(离散≠连续, 放宽容忍)。"""
    spec = {
        "product_type": "barrier", "direction": "buy",
        "start_date": "2021-01-04", "maturity_date": "2022-01-04", "valuation_date": "2021-01-04",
        "s0": 100.0, "spot": 100.0, "r": 0.03, "q": 0.05, "vol": 0.2, "notional": 1_000_000.0,
        "strike_pct": 100, "barrier_pct": 110, "rebate": 0, "parti": 1.0,
        "updown": "up", "inout": "out", "callput": "call",
        "t_step_per_year": 252, "n_paths": 100_000, "seed": 11, "greeks": False, "compute_pnl": False,
    }
    mc = price_deal({**spec, "engine": "mc"}, weekday_cal).price
    an = price_deal({**spec, "engine": "analytic"}, weekday_cal).price
    assert mc > 0 and an > 0
    assert abs(mc - an) / an < 0.35


def test_airbag_runs(weekday_cal):
    spec = {
        "product_type": "airbag", "direction": "buy", "engine": "mc",
        "start_date": "2021-01-04", "maturity_date": "2022-01-04", "valuation_date": "2021-01-04",
        "s0": 100.0, "spot": 100.0, "r": 0.03, "q": 0.05, "vol": 0.2, "notional": 1_000_000.0,
        "strike_pct": 100, "barrier_pct": 70, "knockin_parti": 1.0, "call_parti": 0.7,
        "reset_call_parti": 1.0, "t_step_per_year": 252, "n_paths": 60_000, "seed": 3, "greeks": False, "compute_pnl": False,
    }
    an = price_deal({**spec, "engine": "analytic"}, weekday_cal).price
    mc = price_deal({**spec, "engine": "mc"}, weekday_cal).price
    assert np.isfinite(an) and np.isfinite(mc)


def test_barrier_quad_cross_validation(weekday_cal):
    """闭式解 vs 积分法 vs MC 三法交叉 (容差 30%)。"""
    spec = {
        "product_type": "barrier", "direction": "buy",
        "start_date": "2021-01-04", "maturity_date": "2022-01-04", "valuation_date": "2021-01-04",
        "s0": 100.0, "spot": 100.0, "r": 0.03, "q": 0.05, "vol": 0.2, "notional": 1_000_000.0,
        "strike_pct": 100, "barrier_pct": 110, "rebate": 0, "parti": 1.0,
        "updown": "up", "inout": "out", "callput": "call",
        "t_step_per_year": 252, "n_paths": 80_000, "seed": 11, "greeks": False, "compute_pnl": False,
    }
    mc = price_deal({**spec, "engine": "mc"}, weekday_cal).price
    an = price_deal({**spec, "engine": "analytic"}, weekday_cal).price
    quad = price_deal({**spec, "engine": "quad"}, weekday_cal).price
    assert mc > 0 and an > 0 and quad > 0
    assert abs(mc - an) / an < 0.35
    # 积分法(离散)应更接近 MC 而非连续解析
    assert abs(quad - mc) / mc < 0.35


def test_pnl_baseline_near_zero(weekday_cal):
    spec = {**_golden_spec(), "compute_pnl": True, "n_paths": 20_000, "pnl_paths": 8_000}
    res = price_deal(spec, weekday_cal)
    assert res.chart.get("pnl") is not None
    pnl = [p for p in res.chart["pnl"] if p is not None]
    if pnl:
        assert abs(pnl[0]) < abs(res.price) * 0.5 + 50000


def test_auto_ki_from_path(weekday_cal):
    """模拟路径低于敲入障碍 → 自动 already_ki。"""
    import pandas as pd
    idx = pd.date_range("2021-03-15", "2021-06-01", freq="B")
    # 下跌路径
    closes = pd.Series([6000 - i * 30 for i in range(len(idx))], index=idx)
    spec = {**_golden_spec(), "already_ki": False, "valuation_date": "2021-06-01", "compute_pnl": False}
    spec["s0"] = 6000.0
    spec["spot"] = float(closes.iloc[-1])
    res = price_deal(spec, weekday_cal, market=closes)
    assert res.status in ("knocked_in", "alive", "expired")


def test_vanilla_quad_matches_bs():
    from bp_api.quant.otc.enums import CallPut
    bs = eng.vanilla_bs(s=100, strike=100, r=0.03, q=0.01, vol=0.2, t=1.0, callput=CallPut.CALL)
    quad = eng.vanilla_quad(s=100, strike=100, r=0.03, q=0.01, vol=0.2, t=1.0, callput=CallPut.CALL)
    assert quad == pytest.approx(bs, rel=0.02)


def test_no_lookahead_seed_stable(weekday_cal):
    """相同种子 → 结果确定可复现。"""
    a = price_deal({**_golden_spec(), "seed": 123, "compute_pnl": False}, weekday_cal).price
    b = price_deal({**_golden_spec(), "seed": 123, "compute_pnl": False}, weekday_cal).price
    assert a == pytest.approx(b, rel=1e-9)


def test_knockout_terminated_semantics(weekday_cal):
    """已敲出终止: PV=0, 盈亏=正票息, 图表截断且无敲出后敲入事件。"""
    import pandas as pd

    idx = pd.date_range("2021-03-15", "2022-03-15", freq="B")
    closes = []
    for d in idx:
        if d <= pd.Timestamp("2021-04-15"):
            closes.append(6000 + len(closes) * 20)
        elif d <= pd.Timestamp("2021-10-15"):
            closes.append(6500)
        else:
            closes.append(4000)
    market = pd.Series(closes, index=idx)

    spec = {
        **_golden_spec(),
        "valuation_date": "2021-11-15",
        "already_ki": False,
        "compute_pnl": True,
        "n_paths": 20_000,
        "pnl_paths": 8_000,
        "lock_term_months": 0,
    }
    spec["s0"] = 6000.0
    spec["spot"] = float(market.loc[pd.Timestamp("2021-11-15")])

    res = price_deal(spec, weekday_cal, market=market)
    assert res.status == "knocked_out"
    assert res.price == 0.0
    assert res.present_notional == 0.0
    assert res.current_pnl > 0

    ko_events = [e for e in res.chart["events"] if e["type"] == "knock_out"]
    assert len(ko_events) == 1
    ko_date = ko_events[0]["date"]
    assert ko_events[0].get("terminated") is True

    for e in res.chart["events"]:
        if e["type"] == "knock_in":
            assert e["date"] <= ko_date

    assert res.chart["dates"][-1] <= ko_date
    assert res.chart.get("forward_mean") in ([], None) or all(v is None for v in res.chart["forward_mean"])

    pnl = res.chart.get("pnl")
    assert pnl is not None
    for p in pnl:
        if p is not None:
            assert p == round(p, 2)
    first = next(p for p in pnl if p is not None)
    assert abs(first) < 50_000


def test_chart_truncated_at_valuation(weekday_cal):
    """示意图 / 盈亏仅截至估值日, 无未来函数。"""
    import pandas as pd

    idx = pd.date_range("2021-03-15", "2022-03-15", freq="B")
    market = pd.Series([100.0 + i * 0.1 for i in range(len(idx))], index=idx)
    valuation = "2021-06-15"
    spec = {
        **_golden_spec(),
        "valuation_date": valuation,
        "compute_pnl": True,
        "n_paths": 10_000,
        "pnl_paths": 5_000,
        "greeks": False,
    }
    res = price_deal(spec, weekday_cal, market=market)
    assert res.chart["dates"][-1] <= valuation
    assert res.chart.get("forward_mean") == []
    assert res.chart.get("mean_path") == []
    for e in res.chart["events"]:
        assert e["date"] <= valuation


@pytest.fixture(scope="module")
def cn_est_cal() -> TradingCalendarView:
    """A股预估日历(工作日剔除预估节假日), 用于对照参考文档金标。"""
    from bp_api.quant.otc.holidays import is_estimated_cn_holiday

    days = []
    d = date(2021, 1, 1)
    end = date(2022, 12, 31)
    while d <= end:
        if d.weekday() < 5 and not is_estimated_cn_holiday(d):
            days.append(d)
        d += timedelta(days=1)
    return TradingCalendarView(days)


def _reference_snowball_spec(vol: float) -> dict:
    """固定雪球条款，用于跨版本数值回归。"""
    return {
        "product_type": "snowball",
        "direction": "buy",
        "engine": "mc",
        "start_date": "2021-03-15",
        "maturity_date": "2022-03-15",
        "valuation_date": "2021-03-15",
        "s0": 100.0,
        "spot": 100.0,
        "ko_barrier_pct": 100.0,
        "ki_barrier_pct": 75.0,
        "ki_strike_pct": 100.0,
        "coupon_out": 0.20,
        "coupon_div": 0.20,
        "ko_observation_dates": [
            "2021-04-15", "2021-05-17", "2021-06-15", "2021-07-15", "2021-08-16",
            "2021-09-15", "2021-10-15", "2021-11-15", "2021-12-15", "2022-01-17",
            "2022-02-15", "2022-03-15",
        ],
        "lock_term_months": 0,
        "already_ki": False,
        "r": 0.02,
        "q": 0.0,
        "vol": vol,
        "notional": 1_000_000.0,
        "day_count": "ACT365",
        "t_step_per_year": 252,
        "n_paths": 200_000,
        "seed": 7,
        "greeks": False,
        "compute_pnl": False,
    }


def test_snowball_reference_golden(cn_est_cal):
    """固定随机种子金标: v25%≈7127, v35%≈-22197。"""
    # v=25% → 系统 7127.17 / MC 7079.21
    res25 = price_deal(_reference_snowball_spec(0.25), cn_est_cal)
    assert res25.price == pytest.approx(7127.17, rel=0.08, abs=800)

    # v=35% → 系统 -22196.61 / MC -22171.23
    res35 = price_deal(_reference_snowball_spec(0.35), cn_est_cal)
    assert res35.price < 0
    assert res35.price == pytest.approx(-22196.61, rel=0.08, abs=2000)

    # 波动率越高, 买方雪球价值越低 (敲入承损概率上升)
    assert res35.price < res25.price


def test_chart_no_future_beyond_valuation_alive(weekday_cal):
    """存续单: 图表末日 == 估值日(或之前最近交易日)。"""
    valuation = date(2021, 9, 15)
    spec = {**_golden_spec(), "valuation_date": valuation.isoformat(),
            "compute_pnl": False, "greeks": False, "n_paths": 5_000}
    res = price_deal(spec, weekday_cal)
    last = date.fromisoformat(res.chart["dates"][-1])
    assert last <= valuation
    assert res.meta["valuation_date"] == valuation.isoformat()


def _last_pnl(chart_pnl):
    assert chart_pnl is not None and len(chart_pnl) > 0
    assert chart_pnl[-1] is not None
    return chart_pnl[-1]


def test_chart_pnl_last_equals_current_pnl_alive(weekday_cal):
    """存续单: 示意图末日盈亏 == 结果卡 current_pnl。"""
    import pandas as pd

    idx = pd.date_range("2021-03-15", "2022-03-15", freq="B")
    market = pd.Series([100.0 + i * 0.05 for i in range(len(idx))], index=idx)
    spec = {
        **_golden_spec(),
        "valuation_date": "2021-09-15",
        "compute_pnl": True,
        "n_paths": 10_000,
        "pnl_paths": 5_000,
        "greeks": False,
    }
    res = price_deal(spec, weekday_cal, market=market)
    assert res.current_pnl is not None
    assert _last_pnl(res.chart["pnl"]) == pytest.approx(res.current_pnl, abs=1e-9)
    assert res.current_pnl == round(res.current_pnl, 2)


def test_chart_pnl_last_equals_current_pnl_knockout(weekday_cal):
    """敲出单: 示意图末日盈亏 == 结果卡已实现票息。"""
    import pandas as pd

    idx = pd.date_range("2021-03-15", "2022-03-15", freq="B")
    closes = []
    for d in idx:
        if d <= pd.Timestamp("2021-04-15"):
            closes.append(6000 + len(closes) * 20)
        elif d <= pd.Timestamp("2021-10-15"):
            closes.append(6500)
        else:
            closes.append(4000)
    market = pd.Series(closes, index=idx)
    spec = {
        **_golden_spec(),
        "valuation_date": "2021-11-15",
        "already_ki": False,
        "compute_pnl": True,
        "n_paths": 10_000,
        "pnl_paths": 5_000,
        "lock_term_months": 0,
        "s0": 6000.0,
        "spot": float(market.loc[pd.Timestamp("2021-11-15")]),
    }
    res = price_deal(spec, weekday_cal, market=market)
    assert res.status == "knocked_out"
    assert res.current_pnl is not None and res.current_pnl > 0
    assert _last_pnl(res.chart["pnl"]) == pytest.approx(res.current_pnl, abs=1e-9)


def test_ko_only_on_observation_day_not_intraday_cross(weekday_cal):
    """观察日之间上穿敲出线不算敲出; 仅观察日 S>=KO 才终止, 且仅一个敲出事件。"""
    import pandas as pd

    # 敲出线 = 103 (s0=100). 4月中途曾到 110, 但 4/15 观察日收于 102 → 不敲出;
    # 5/17 观察日收于 105 → 敲出终止。
    idx = pd.date_range("2021-03-15", "2021-06-30", freq="B")
    closes = []
    for d in idx:
        ds = d.date()
        if ds < date(2021, 4, 10):
            closes.append(100.0)
        elif ds < date(2021, 4, 15):
            closes.append(110.0)  # 观察日之间上穿 KO
        elif ds == date(2021, 4, 15):
            closes.append(102.0)  # 观察日未达 KO
        elif ds < date(2021, 5, 17):
            closes.append(101.0)
        elif ds == date(2021, 5, 17):
            closes.append(105.0)  # 观察日敲出
        else:
            closes.append(90.0)   # 敲出后下跌 — 不应再产生敲入事件
    market = pd.Series(closes, index=idx)

    spec = {
        **_golden_spec(),
        "ko_barrier_pct": 103.0,
        "ki_barrier_pct": 75.0,
        "valuation_date": "2021-06-15",
        "already_ki": False,
        "compute_pnl": False,
        "greeks": False,
        "n_paths": 5_000,
        "lock_term_months": 0,
        "s0": 100.0,
        "spot": 90.0,
    }
    res = price_deal(spec, weekday_cal, market=market)
    assert res.status == "knocked_out"
    ko_events = [e for e in res.chart["events"] if e["type"] == "knock_out"]
    assert len(ko_events) == 1
    assert ko_events[0]["date"] == "2021-05-17"
    assert ko_events[0].get("terminated") is True
    assert res.chart["dates"][-1] == "2021-05-17"
    assert "2021-05-17" in (res.chart.get("ko_observation_dates") or [])
    # 敲出后路径下跌不应再出现敲入事件
    assert not any(e["type"] == "knock_in" and e["date"] > "2021-05-17" for e in res.chart["events"])
    # 4 月中途上穿不产生敲出
    assert not any(e["type"] == "knock_out" and e["date"].startswith("2021-04") for e in res.chart["events"])


# ---------------------------------------------------------------------------
# 簿记估值落库 + Redis (mock, 无真实 DB)
# ---------------------------------------------------------------------------
def test_save_deal_valuation_writes_history_and_cache(monkeypatch):
    from unittest.mock import MagicMock

    from bp_api import repositories_otc as rotc

    cur = MagicMock()
    conn = MagicMock()
    conn.cursor.return_value.__enter__ = MagicMock(return_value=cur)
    conn.cursor.return_value.__exit__ = MagicMock(return_value=False)

    cached: dict = {}

    def fake_set(key, value, ttl_seconds=300):
        cached[key] = (value, ttl_seconds)

    monkeypatch.setattr(rotc.cache, "set_json", fake_set)
    monkeypatch.setattr(rotc.cache, "get_json", lambda key: cached.get(key, (None,))[0])
    monkeypatch.setattr(rotc.cache, "delete", lambda key: cached.pop(key, None))

    result = {
        "price": 123.45,
        "present_notional": 1_000_000.0,
        "greeks": {"delta": 0.1},
        "status": "alive",
        "current_pnl": -10.0,
        "chart": {"dates": ["2021-03-15"]},
    }
    rotc.save_deal_valuation(conn, 42, result, task_id="task-abc")

    assert cur.execute.call_count == 2
    update_sql = cur.execute.call_args_list[0][0][0]
    insert_sql = cur.execute.call_args_list[1][0][0]
    assert "UPDATE bp_otc_deal" in update_sql
    assert "INSERT INTO bp_otc_deal_price_history" in insert_sql
    hist_params = cur.execute.call_args_list[1][0][1]
    assert hist_params[0] == 42
    assert hist_params[5] == "task-abc"
    key = rotc._deal_result_cache_key(42)
    assert key in cached
    assert cached[key][0]["price"] == 123.45
    assert cached[key][1] == rotc._OTC_DEAL_RESULT_TTL


def test_get_otc_deal_prefers_redis_cache(monkeypatch):
    from unittest.mock import MagicMock

    from bp_api import repositories_otc as rotc

    row = (
        7, "demo", "snowball", "mc", "000905", "cn_index_em", {},
        False, 1, 10.0, 1e6, {}, "alive", None,
        {"price": 10.0, "status": "alive"}, None, None,
    )
    cur = MagicMock()
    cur.fetchone.return_value = row
    conn = MagicMock()
    conn.cursor.return_value.__enter__ = MagicMock(return_value=cur)
    conn.cursor.return_value.__exit__ = MagicMock(return_value=False)

    cached_result = {"price": 99.0, "status": "knocked_out", "chart": {}}
    monkeypatch.setattr(
        rotc.cache, "get_json",
        lambda key: cached_result if key == rotc._deal_result_cache_key(7) else None,
    )
    monkeypatch.setattr(rotc.cache, "set_json", lambda *a, **k: None)

    deal = rotc.get_otc_deal(conn, 7)
    assert deal is not None
    assert deal["last_result"]["price"] == 99.0
    assert deal["last_result"]["status"] == "knocked_out"


def test_reorder_otc_deals_upserts_visible_only():
    from unittest.mock import MagicMock

    from bp_api import repositories_otc as rotc

    cur = MagicMock()
    # visible deals: 1, 2
    cur.fetchall.return_value = [(1,), (2,)]
    conn = MagicMock()
    conn.cursor.return_value.__enter__ = MagicMock(return_value=cur)
    conn.cursor.return_value.__exit__ = MagicMock(return_value=False)

    rotc.reorder_otc_deals(conn, user_id=9, ordered_ids=[2, 1, 99])
    # 1 SELECT + 2 INSERTs (99 skipped)
    assert cur.execute.call_count == 3
    insert_calls = [c[0][0] for c in cur.execute.call_args_list[1:]]
    assert all("INSERT INTO bp_user_otc_deal_order" in sql for sql in insert_calls)
    params = [c[0][1] for c in cur.execute.call_args_list[1:]]
    assert params[0] == (9, 2, 0)
    assert params[1] == (9, 1, 1)
