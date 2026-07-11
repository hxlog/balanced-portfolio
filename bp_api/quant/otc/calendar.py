"""交易日历视图 + 计息约定 + 观察日生成/递延。

- TradingCalendarView: 有序交易日列表, 支持 O(log n) 的成员判断/偏移量查询/递延。
- year_fraction: ACT/365, ACT/360, BUS/252 计息年化。
- gen_ko_observation_dates: 按频率生成敲出观察日(月/季), 非交易日按 following 递延。
- business_offset: 某交易日相对估值日的路径下标(= (估值日, 目标日] 内交易日数)。
"""

from __future__ import annotations

import bisect
from datetime import date, timedelta
from typing import Iterable, Optional

from .enums import DayCount


def _add_months(d: date, months: int) -> date:
    """d + months 个自然月(月末对齐: 若目标月无该日则取当月最后一天)。"""
    m = d.month - 1 + months
    year = d.year + m // 12
    month = m % 12 + 1
    # 该月天数
    if month == 12:
        last = 31
    else:
        last = (date(year, month + 1, 1) - timedelta(days=1)).day
    return date(year, month, min(d.day, last))


class TradingCalendarView:
    """一段有序、去重的交易日集合的只读视图。"""

    def __init__(self, days: Iterable[date]):
        self._days: list[date] = sorted(set(days))
        self._set: set[date] = set(self._days)

    def __len__(self) -> int:
        return len(self._days)

    @property
    def days(self) -> list[date]:
        return self._days

    @property
    def first(self) -> Optional[date]:
        return self._days[0] if self._days else None

    @property
    def last(self) -> Optional[date]:
        return self._days[-1] if self._days else None

    def is_trading_day(self, d: date) -> bool:
        return d in self._set

    def next_trading_day(self, d: date, inclusive: bool = True) -> Optional[date]:
        """>= d (inclusive) 或 > d 的最近交易日。"""
        i = bisect.bisect_left(self._days, d)
        if inclusive:
            if i < len(self._days):
                return self._days[i]
            return None
        # strictly greater
        if i < len(self._days) and self._days[i] == d:
            i += 1
        return self._days[i] if i < len(self._days) else None

    def prev_trading_day(self, d: date, inclusive: bool = True) -> Optional[date]:
        """<= d (inclusive) 或 < d 的最近交易日。"""
        i = bisect.bisect_right(self._days, d)
        if not inclusive and i > 0 and self._days[i - 1] == d:
            i -= 1
        return self._days[i - 1] if i > 0 else None

    def roll(self, d: date, convention: str = "following") -> Optional[date]:
        """把 d 递延到交易日。following / previous / modified_following。"""
        if d in self._set:
            return d
        if convention == "previous":
            return self.prev_trading_day(d)
        nxt = self.next_trading_day(d)
        if convention == "modified_following" and nxt is not None and nxt.month != d.month:
            return self.prev_trading_day(d)
        return nxt

    def sessions_in(
        self,
        start: date,
        end: date,
        include_start: bool = False,
        include_end: bool = True,
    ) -> list[date]:
        """区间内交易日列表(默认 (start, end])。"""
        lo = bisect.bisect_left(self._days, start)
        hi = bisect.bisect_right(self._days, end)
        seg = self._days[lo:hi]
        if seg and not include_start and seg[0] == start:
            seg = seg[1:]
        if seg and not include_end and seg[-1] == end:
            seg = seg[:-1]
        return seg

    def business_offset(self, valuation: date, target: date) -> int:
        """target 相对 valuation 的路径下标 = (valuation, target] 内交易日数。

        约定 st[:, 0] = 估值日价格, st[:, k] = 估值日之后第 k 个交易日的价格,
        因此某观察日的路径下标恰为该值。
        """
        return len(self.sessions_in(valuation, target, include_start=False, include_end=True))


def year_fraction(
    dc: DayCount | str,
    start: date,
    end: date,
    cal: Optional[TradingCalendarView] = None,
) -> float:
    """计息年化因子。BUS252 需要日历(退化时用 250/365 近似)。"""
    dcv = dc.value if isinstance(dc, DayCount) else str(dc)
    days = (end - start).days
    if dcv == DayCount.ACT365.value:
        return days / 365.0
    if dcv == DayCount.ACT360.value:
        return days / 360.0
    if dcv == DayCount.BUS252.value:
        if cal is not None:
            n = len(cal.sessions_in(start, end, include_start=False, include_end=True))
            return n / 252.0
        return days / 365.0 * 250.0 / 252.0
    return days / 365.0


def gen_ko_observation_dates(
    start: date,
    maturity: date,
    cal: TradingCalendarView,
    freq_months: int = 1,
    lock_term_months: int = 0,
    convention: str = "following",
) -> list[date]:
    """生成敲出观察日: 自 start 起每 freq_months 个自然月一个观察点, 非交易日 following 递延。

    - 锁定期(lock_term_months): 前 N 个月不观察敲出 → 剔除 <= start+lock 的观察点。
    - 末点强制为 maturity(递延后的交易日)。
    """
    lock_end = _add_months(start, lock_term_months) if lock_term_months > 0 else start
    raw: list[date] = []
    k = freq_months
    while True:
        d = _add_months(start, k)
        if d >= maturity:
            break
        raw.append(d)
        k += freq_months

    rolled: list[date] = []
    seen: set[date] = set()
    for d in raw:
        if d <= lock_end:
            continue
        rd = cal.roll(d, convention)
        if rd is None or rd >= maturity:
            continue
        if rd not in seen:
            seen.add(rd)
            rolled.append(rd)

    mat = cal.roll(maturity, convention) or maturity
    if mat not in seen:
        rolled.append(mat)
    rolled.sort()
    return rolled


def roll_dates(
    dates: Iterable[date], cal: TradingCalendarView, convention: str = "following"
) -> list[dict]:
    """把一组请求观察日递延到交易日, 返回 {requested, effective, rolled} 列表。"""
    out: list[dict] = []
    for d in dates:
        rd = cal.roll(d, convention)
        out.append(
            {
                "requested": d.isoformat(),
                "effective": rd.isoformat() if rd else None,
                "rolled": bool(rd and rd != d),
            }
        )
    return out
