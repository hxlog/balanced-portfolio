"""A股交易日历: 用于判断"期望最新交易日"与是否需要增量更新。

数据源: ak.tool_trade_date_hist_sina() (历史+未来交易日列表)。
加载一次后缓存于进程内。

收盘确认: 日 K 源在盘中会把「最新价」填进当日 close。沪深现货收盘 15:00,
本模块在 15:10(CST) 后才把「今天」视为可落库/可展示的正式收盘日。
"""

from __future__ import annotations

import logging
import os
from datetime import date, datetime, time, timedelta, timezone
from typing import Optional

import akshare as ak

logger = logging.getLogger(__name__)

CST = timezone(timedelta(hours=8))

# 现货收盘 15:00 后留短缓冲, 再认当日日 K 收盘价; 可用 BP_CLOSE_CONFIRM_HHMM=1510 覆盖。
def _parse_close_confirm() -> time:
    raw = (os.getenv("BP_CLOSE_CONFIRM_HHMM") or "1510").strip()
    try:
        if len(raw) == 4 and raw.isdigit():
            return time(int(raw[:2]), int(raw[2:]))
    except ValueError:
        pass
    return time(15, 10)


CLOSE_CONFIRM_TIME: time = _parse_close_confirm()


def now_cst(now: datetime | None = None) -> datetime:
    """当前(或给定)时刻转到 Asia/Shanghai。naive 视为已是 CST。"""
    if now is None:
        return datetime.now(CST)
    if now.tzinfo is None:
        return now.replace(tzinfo=CST)
    return now.astimezone(CST)


def session_close_confirmed_at(now: datetime | None = None) -> bool:
    """此刻是否已过当日收盘确认时刻(15:10 CST)。"""
    n = now_cst(now)
    return n.timetz().replace(tzinfo=None) >= CLOSE_CONFIRM_TIME


def close_confirm_deadline(trade_date: date) -> datetime:
    """该交易日正式收盘价可被采信的最早时刻(CST)。"""
    return datetime.combine(trade_date, CLOSE_CONFIRM_TIME, tzinfo=CST)


def is_trade_date_close_confirmed(
    trade_date: date,
    *,
    now: datetime | None = None,
    today: date | None = None,
) -> bool:
    """该 trade_date 的日 K close 是否已可视为正式收盘价。

    - 严格早于「今天」: 历史日, 恒为 True
    - 严格晚于「今天」: 未来日, 恒为 False
    - 等于「今天」: 仅当 now >= 当日 15:10 CST
    """
    n = now_cst(now)
    t = today if today is not None else n.date()
    if trade_date < t:
        return True
    if trade_date > t:
        return False
    return session_close_confirmed_at(n)


def filter_confirmed_trade_dates(
    dates: list[date],
    *,
    now: datetime | None = None,
    today: date | None = None,
) -> list[date]:
    """保留已确认收盘的交易日(保持原序)。"""
    return [
        d for d in dates
        if is_trade_date_close_confirmed(d, now=now, today=today)
    ]


class TradingCalendar:
    def __init__(self) -> None:
        self._dates: list[date] = []
        self._date_set: set[date] = set()

    def load(self) -> None:
        df = ak.tool_trade_date_hist_sina()
        col = df.columns[0]  # 通常为 'trade_date'
        dates: list[date] = []
        for v in df[col].tolist():
            if isinstance(v, date) and not isinstance(v, datetime):
                dates.append(v)
            elif isinstance(v, datetime):
                dates.append(v.date())
            else:
                try:
                    dates.append(date.fromisoformat(str(v)[:10]))
                except ValueError:
                    continue
        self._dates = sorted(dates)
        self._date_set = set(self._dates)
        logger.info("交易日历已加载: %d 个交易日 (%s ~ %s)",
                    len(self._dates),
                    self._dates[0] if self._dates else "-",
                    self._dates[-1] if self._dates else "-")

    def is_trading_day(self, d: date) -> bool:
        return d in self._date_set

    @property
    def dates(self) -> list[date]:
        return self._dates

    def trading_days_between(self, start: date, end: date) -> list[date]:
        """返回 [start, end] 闭区间内的所有 A股交易日(升序)。"""
        return [d for d in self._dates if start <= d <= end]

    def latest_trading_day_on_or_before(self, d: date) -> Optional[date]:
        """返回 <= d 的最近交易日。"""
        candidate: Optional[date] = None
        for td in reversed(self._dates):
            if td <= d:
                candidate = td
                break
        return candidate

    def expected_latest(self, today: date, lag_days: int = 0) -> Optional[date]:
        """期望已存在的最新交易日: today 回退 lag_days 自然日后, 取最近交易日。

        默认 lag_days=0: 不区分是否已收盘。需要收盘确认时请用 confirmed_expected_latest。
        """
        ref = today - timedelta(days=lag_days)
        return self.latest_trading_day_on_or_before(ref)

    def confirmed_expected_latest(
        self,
        today: date,
        lag_days: int = 0,
        *,
        now: datetime | None = None,
    ) -> Optional[date]:
        """与 expected_latest 相同, 但今日未过 15:10 时回退到上一交易日。

        防止盘中把「形成中」的日 K close(实为最新价)当作正式收盘入库/展示。
        """
        base = self.expected_latest(today, lag_days)
        if base is None:
            return None
        if base == today and not is_trade_date_close_confirmed(
            today, now=now, today=today
        ):
            return self.latest_trading_day_on_or_before(today - timedelta(days=1))
        return base
