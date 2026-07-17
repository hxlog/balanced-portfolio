"""收盘确认闸门: 盘中日 K close ≠ 正式收盘价。

运行: python -m pytest bp_api/tests/test_close_confirm.py -q
"""

from __future__ import annotations

from datetime import date, datetime, time, timedelta
from zoneinfo import ZoneInfo

import pandas as pd
import pytest

CST = ZoneInfo("Asia/Shanghai")


def _dt(d: date, hh: int, mm: int = 0) -> datetime:
    return datetime(d.year, d.month, d.day, hh, mm, tzinfo=CST)


class TestCloseConfirmHelpers:
    def test_historical_always_confirmed(self):
        from bp_ingest.calendar import is_trade_date_close_confirmed

        today = date(2026, 7, 17)
        now = _dt(today, 10, 0)
        assert is_trade_date_close_confirmed(date(2026, 7, 16), now=now, today=today)

    def test_today_before_1510_unconfirmed(self):
        from bp_ingest.calendar import is_trade_date_close_confirmed

        today = date(2026, 7, 17)
        now = _dt(today, 15, 9)
        assert not is_trade_date_close_confirmed(today, now=now, today=today)

    def test_today_at_1510_confirmed(self):
        from bp_ingest.calendar import is_trade_date_close_confirmed

        today = date(2026, 7, 17)
        now = _dt(today, 15, 10)
        assert is_trade_date_close_confirmed(today, now=now, today=today)

    def test_future_unconfirmed(self):
        from bp_ingest.calendar import is_trade_date_close_confirmed

        today = date(2026, 7, 17)
        now = _dt(today, 16, 0)
        assert not is_trade_date_close_confirmed(date(2026, 7, 18), now=now, today=today)

    def test_filter_confirmed_trade_dates(self):
        from bp_ingest.calendar import filter_confirmed_trade_dates

        today = date(2026, 7, 17)
        now = _dt(today, 14, 0)
        dates = [today, date(2026, 7, 16), date(2026, 7, 15)]
        assert filter_confirmed_trade_dates(dates, now=now, today=today) == [
            date(2026, 7, 16), date(2026, 7, 15),
        ]


class TestConfirmedExpectedLatest:
    def _cal_with(self, days: list[date]):
        from bp_ingest.calendar import TradingCalendar

        cal = TradingCalendar()
        cal._dates = sorted(days)
        cal._date_set = set(days)
        return cal

    def test_rolls_back_before_close(self):
        cal = self._cal_with([
            date(2026, 7, 15), date(2026, 7, 16), date(2026, 7, 17),
        ])
        today = date(2026, 7, 17)
        now = _dt(today, 14, 30)
        assert cal.confirmed_expected_latest(today, 0, now=now) == date(2026, 7, 16)

    def test_allows_today_after_close(self):
        cal = self._cal_with([
            date(2026, 7, 15), date(2026, 7, 16), date(2026, 7, 17),
        ])
        today = date(2026, 7, 17)
        now = _dt(today, 15, 10)
        assert cal.confirmed_expected_latest(today, 0, now=now) == today

    def test_lag_days_still_respected(self):
        cal = self._cal_with([
            date(2026, 7, 15), date(2026, 7, 16), date(2026, 7, 17),
        ])
        today = date(2026, 7, 17)
        now = _dt(today, 16, 0)
        # lag=1 → 期望 7/16, 与收盘确认无关
        assert cal.confirmed_expected_latest(today, 1, now=now) == date(2026, 7, 16)


class TestDropUnconfirmedBars:
    def test_drops_today_before_close(self):
        from bp_ingest.ingest import _drop_unconfirmed_today_bars

        today = date(2026, 7, 17)
        df = pd.DataFrame({
            "trade_date": [date(2026, 7, 16), today],
            "close": [100.0, 999.0],
        })
        out = _drop_unconfirmed_today_bars(df, today, now=_dt(today, 14, 0))
        assert list(out["trade_date"]) == [date(2026, 7, 16)]
        assert list(out["close"]) == [100.0]

    def test_keeps_today_after_close(self):
        from bp_ingest.ingest import _drop_unconfirmed_today_bars

        today = date(2026, 7, 17)
        df = pd.DataFrame({
            "trade_date": [date(2026, 7, 16), today],
            "close": [100.0, 4529.10],
        })
        out = _drop_unconfirmed_today_bars(df, today, now=_dt(today, 15, 10))
        assert len(out) == 2


class TestPickEffectiveWithMaxConfirmed:
    def test_skips_unconfirmed_today(self):
        from bp_api.cffex import pick_effective_trade_date

        t = date(2026, 7, 17)
        t1 = date(2026, 7, 16)
        vars_all = {"IF", "IH", "IC", "IM"}
        spots_all = {"000300", "000016", "000905", "000852"}
        futures = {t: vars_all, t1: vars_all}
        spots = {t: spots_all, t1: spots_all}
        # 盘中: max_confirmed = 昨日 → 不能选今日(即使库里已有脏四指数)
        picked = pick_effective_trade_date(
            [t, t1], futures, spots, max_confirmed_date=t1,
        )
        assert picked == t1

    def test_allows_today_when_confirmed(self):
        from bp_api.cffex import pick_effective_trade_date

        t = date(2026, 7, 17)
        vars_all = {"IF", "IH", "IC", "IM"}
        spots_all = {"000300", "000016", "000905", "000852"}
        picked = pick_effective_trade_date(
            [t], {t: vars_all}, {t: spots_all}, max_confirmed_date=t,
        )
        assert picked == t


class TestForceRefreshIndependentOfLag:
    """即使 lag_days 把 expected 挡在 T-1, 今日盘中脏行也必须收盘后重拉。"""

    def test_needs_refresh_when_updated_before_confirm(self, monkeypatch):
        from bp_ingest import ingest as ing
        from bp_ingest.calendar import close_confirm_deadline

        today = date(2026, 7, 17)
        deadline = close_confirm_deadline(today)
        early = deadline - timedelta(hours=5)

        class _FakeConn:
            pass

        def fake_ua(conn, symbol, source, trade_date):
            assert trade_date == today
            return early

        monkeypatch.setattr(ing.db, "get_quote_updated_at", fake_ua)
        assert ing._needs_post_close_refresh(
            _FakeConn(), "000300", "cn_index_em", today, now=_dt(today, 16, 0)
        )

    def test_no_refresh_when_updated_after_confirm(self, monkeypatch):
        from bp_ingest import ingest as ing
        from bp_ingest.calendar import close_confirm_deadline

        today = date(2026, 7, 17)
        deadline = close_confirm_deadline(today)
        late = deadline + timedelta(minutes=5)

        class _FakeConn:
            pass

        monkeypatch.setattr(
            ing.db, "get_quote_updated_at", lambda *a, **k: late
        )
        assert not ing._needs_post_close_refresh(
            _FakeConn(), "000300", "cn_index_em", today, now=_dt(today, 16, 0)
        )


class TestCloseConfirmDeadline:
    def test_deadline_is_1510_cst(self):
        from bp_ingest.calendar import CLOSE_CONFIRM_TIME, close_confirm_deadline

        assert CLOSE_CONFIRM_TIME == time(15, 10)
        d = close_confirm_deadline(date(2026, 7, 17))
        assert d.hour == 15 and d.minute == 10
        assert d.tzinfo is not None
        assert d.utcoffset() == timedelta(hours=8)
