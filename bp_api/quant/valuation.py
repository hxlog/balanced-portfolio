"""估值分位与区间统计纯函数（无 IO / 无 DB）。

分位算法的唯一入口（见 ``docs/index-valuation/05-master-plan.md`` §3.5）::

    pct = (count(<x) + 0.5 * count(==x)) / N * 100
        = (count(<=x) - 0.5 * count(==x)) / N * 100

并列值取中点 rank（midrank）：若直接把所有等于 x 的值算作「严格小于」，
并列值会被系统性低估；若算作「小于等于」，又会被系统性高估。

约定：
- 缺失即缺失：``None`` / ``NaN`` 不计入样本，也不填 0。
- 当前值取窗口内**最后一个有效值**（``window_slice`` 保证按日期升序）。
- p20/p50/p80 采用线性插值（Excel ``PERCENTILE.INC`` /
  ``numpy.percentile(..., method="linear")``）。
"""

from __future__ import annotations

import math
from datetime import date
from statistics import fmean, stdev
from typing import Optional, Sequence

# 分位样本量门槛：有效样本不足时不输出 pct。
# 估值序列来自平安，频率为周频（约 52 点/年），因此 1 年窗口天然凑不满 120 个点，
# 对 1y 采用 40 点的门槛（≥40 个周频样本仍可给出有意义的序位），其余窗口保持 120。
MIN_SAMPLE = 120
MIN_SAMPLE_BY_WINDOW = {"1y": 40, "3y": 120, "5y": 120, "10y": 120, "all": 120}


def min_sample_for(window: str) -> int:
    """按窗口返回最小有效样本数。"""
    return MIN_SAMPLE_BY_WINDOW.get(window, MIN_SAMPLE)

_WINDOW_YEARS = {"1y": 1, "3y": 3, "5y": 5, "10y": 10}

LEVEL_LOW = "低估"
LEVEL_NEUTRAL = "中性"
LEVEL_HIGH = "高估"


def _is_valid(value: Optional[float]) -> bool:
    """有效数值 = 非 None 且非 NaN。"""
    return value is not None and not math.isnan(value)


def _clean(values: Sequence[Optional[float]]) -> list[float]:
    """剔除 None/NaN，并统一为 float。"""
    return [float(v) for v in values if _is_valid(v)]


def percentile(values: Sequence[float], x: float) -> Optional[float]:
    """x 在 values 中的分位（0~100）。

    ``(count(<x) + 0.5*count(==x)) / N * 100``；N=0 或 x 缺失返回 None。
    """
    if not _is_valid(x):
        return None
    vals = _clean(values)
    n = len(vals)
    if n == 0:
        return None
    less = sum(1 for v in vals if v < x)
    equal = sum(1 for v in vals if v == x)
    return (less + 0.5 * equal) / n * 100.0


def _shift_years(d: date, years: int) -> date:
    """按自然年平移日期；2/29 落到非闰年时回退到 2/28。"""
    try:
        return d.replace(year=d.year + years)
    except ValueError:
        return d.replace(year=d.year + years, month=2, day=28)


def window_slice(
    series: Sequence[tuple[date, Optional[float]]],
    as_of: date,
    window: str,
) -> list[float]:
    """截取 ``[as_of - window, as_of]`` 闭区间内的有效值，按日期升序返回。

    ``window`` 接受 ``1y`` / ``3y`` / ``5y`` / ``10y`` / ``all``；``all`` 表示
    as_of 之前的全部历史。``as_of`` 当日及其之前（含窗口下边界当日）均包含。
    """
    if window == "all":
        start: Optional[date] = None
    elif window in _WINDOW_YEARS:
        start = _shift_years(as_of, -_WINDOW_YEARS[window])
    else:
        raise ValueError(f"unsupported window: {window!r}")

    out: list[float] = []
    for trade_date, value in sorted(series, key=lambda item: item[0]):
        if trade_date > as_of:
            continue
        if start is not None and trade_date < start:
            continue
        if not _is_valid(value):
            continue
        out.append(float(value))
    return out


def _quantile(sorted_values: Sequence[float], p: float) -> Optional[float]:
    """线性插值分位点（PERCENTILE.INC / numpy method='linear'）。"""
    n = len(sorted_values)
    if n == 0:
        return None
    if n == 1:
        return float(sorted_values[0])
    pos = (n - 1) * p
    lo = math.floor(pos)
    hi = math.ceil(pos)
    if lo == hi:
        return float(sorted_values[lo])
    frac = pos - lo
    return float(sorted_values[lo] + frac * (sorted_values[hi] - sorted_values[lo]))


def summarize(values: Sequence[float], min_sample: int = MIN_SAMPLE) -> dict:
    """窗口统计量。

    返回键：``pct/mean/sd/p20/p50/p80/min/max/sample_size``。
    - ``pct`` 为最后一个有效值在该窗口内的分位；
    - ``sd`` 为样本标准差（n-1），n<2 时为 None；
    - 有效样本 < ``min_sample``（默认 ``MIN_SAMPLE``）时 ``pct=None`` 并带
      ``reason="insufficient_sample"``。
    """
    vals = _clean(values)
    n = len(vals)
    if n == 0:
        return {
            "pct": None,
            "mean": None,
            "sd": None,
            "p20": None,
            "p50": None,
            "p80": None,
            "min": None,
            "max": None,
            "sample_size": 0,
            "reason": "insufficient_sample",
        }

    ordered = sorted(vals)
    out: dict = {
        "pct": None,
        "mean": fmean(vals),
        "sd": stdev(vals) if n >= 2 else None,
        "p20": _quantile(ordered, 0.20),
        "p50": _quantile(ordered, 0.50),
        "p80": _quantile(ordered, 0.80),
        "min": float(ordered[0]),
        "max": float(ordered[-1]),
        "sample_size": n,
    }
    if n < min_sample:
        out["reason"] = "insufficient_sample"
    else:
        out["pct"] = percentile(vals, vals[-1])
    return out


def erp(dividend_yield: Optional[float], bond10y: Optional[float]) -> Optional[float]:
    """风险溢价（百分点）= 股息率 * 100 - 十年期国债收益率。

    股息率以小数表示（0.0368 = 3.68%），bond10y 已是百分数（1.6123）。
    任一侧缺失（None/NaN）返回 None；不做跨日填充。
    """
    if not _is_valid(dividend_yield) or not _is_valid(bond10y):
        return None
    return dividend_yield * 100.0 - bond10y


def level_of(
    pct: Optional[float],
    low: float = 20.0,
    high: float = 80.0,
) -> Optional[str]:
    """分位分级：``[0, low)`` 低估、``[low, high)`` 中性、``[high, 100]`` 高估。"""
    if pct is None or math.isnan(pct):
        return None
    if pct < low:
        return LEVEL_LOW
    if pct < high:
        return LEVEL_NEUTRAL
    return LEVEL_HIGH
