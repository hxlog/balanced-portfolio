"""A股交易日历: 用于判断"期望最新交易日"与是否需要增量更新。

数据源: ak.tool_trade_date_hist_sina() (历史+未来交易日列表)。
加载一次后缓存于进程内。
"""

from __future__ import annotations

import logging
from datetime import date, datetime
from typing import Optional

import akshare as ak

logger = logging.getLogger(__name__)


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

        默认 lag_days=0: 当日收盘后数据即可被发现并拉取。
        """
        from datetime import timedelta

        ref = today - timedelta(days=lag_days)
        return self.latest_trading_day_on_or_before(ref)
