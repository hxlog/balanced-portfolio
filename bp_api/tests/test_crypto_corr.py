"""加密相关性预计算引擎 — 纯逻辑函数测试 (无 DB/Redis 依赖)。

测试:
  - _canonical_as_of_ts: 16:00 ET → UTC (DST 自洽)
  - pick_effective_trade_date: 6 资产齐全 + max_confirmed_date 门槛 (镜像 CFFEX 同名函数)
  - _pearson_r / _log_returns / _rolling_corr: 相关性数学

运行: python -m pytest bp_api/tests/test_crypto_corr.py -q
"""

from __future__ import annotations

from datetime import date
from zoneinfo import ZoneInfo

import numpy as np
import pytest
import pandas as pd


class TestCanonicalAsOf:
    def test_summer_edt(self):
        from bp_ingest.crypto_corr import _canonical_as_of_ts
        # 2026-07-24 是 EDT (UTC-4): 16:00 ET = 20:00 UTC
        ts = _canonical_as_of_ts(date(2026, 7, 24))
        assert ts.tzinfo is not None
        assert ts.astimezone(ZoneInfo("UTC")).hour == 20
        assert ts.astimezone(ZoneInfo("UTC")).minute == 0

    def test_winter_est(self):
        from bp_ingest.crypto_corr import _canonical_as_of_ts
        # 2026-01-15 是 EST (UTC-5): 16:00 ET = 21:00 UTC
        ts = _canonical_as_of_ts(date(2026, 1, 15))
        assert ts.astimezone(ZoneInfo("UTC")).hour == 21

    def test_et_hour_is_16(self):
        from bp_ingest.crypto_corr import _canonical_as_of_ts, NY_TZ
        ts = _canonical_as_of_ts(date(2026, 7, 24))
        et = ts.astimezone(NY_TZ)
        assert et.hour == 16 and et.minute == 0


class TestPickEffectiveTradeDate:
    def _panel(self):
        from bp_ingest.crypto_corr import ALL_PANEL_SYMBOLS
        return list(ALL_PANEL_SYMBOLS)

    def test_all_present_picks_latest(self):
        from bp_ingest.crypto_corr import pick_effective_trade_date
        panel = set(self._panel())
        t = date(2026, 7, 17)
        t1 = date(2026, 7, 16)
        by_date = {t: panel, t1: panel}
        assert pick_effective_trade_date([t, t1], by_date, list(panel)) == t

    def test_missing_one_rolls_back(self):
        from bp_ingest.crypto_corr import pick_effective_trade_date
        panel = set(self._panel())
        t = date(2026, 7, 17)
        t1 = date(2026, 7, 16)
        # T 日缺 AU0 → 不齐全, 回退到 T-1
        by_date = {t: panel - {"AU0"}, t1: panel}
        assert pick_effective_trade_date([t, t1], by_date, list(panel)) == t1

    def test_max_confirmed_excludes_today(self):
        from bp_ingest.crypto_corr import pick_effective_trade_date
        panel = set(self._panel())
        t = date(2026, 7, 17)
        t1 = date(2026, 7, 16)
        by_date = {t: panel, t1: panel}
        # 盘中: max_confirmed = 昨日 → 不能选今日
        assert pick_effective_trade_date([t, t1], by_date, list(panel), max_confirmed_date=t1) == t1

    def test_none_when_no_complete_day(self):
        from bp_ingest.crypto_corr import pick_effective_trade_date
        panel = set(self._panel())
        t = date(2026, 7, 17)
        by_date = {t: panel - {"AU0"}}
        assert pick_effective_trade_date([t], by_date, list(panel)) is None

    def test_iterates_in_given_order(self):
        """candidate_dates 须降序; 传入乱序则按给定顺序取首个齐全者(非最新)。"""
        from bp_ingest.crypto_corr import pick_effective_trade_date
        panel = set(self._panel())
        t = date(2026, 7, 17)
        t1 = date(2026, 7, 16)
        by_date = {t: panel, t1: panel}
        # 升序传入: 先 t1 (齐全) → 返回 t1, 而非最新的 t
        assert pick_effective_trade_date([t1, t], by_date, list(panel)) == t1


class TestCorrMath:
    def test_pearson_perfect_positive(self):
        from bp_ingest.crypto_corr import _pearson_r
        r = _pearson_r(np.array([1.0, 2.0, 3.0, 4.0]), np.array([2.0, 4.0, 6.0, 8.0]))
        assert abs(r - 1.0) < 1e-9

    def test_pearson_perfect_negative(self):
        from bp_ingest.crypto_corr import _pearson_r
        r = _pearson_r(np.array([1.0, 2.0, 3.0, 4.0]), np.array([4.0, 3.0, 2.0, 1.0]))
        assert abs(r - (-1.0)) < 1e-9

    def test_log_returns(self):
        from bp_ingest.crypto_corr import _log_returns
        s = pd.Series(
            [100.0, 110.0, 105.0],
            index=pd.to_datetime(["2026-01-01", "2026-01-02", "2026-01-03"]),
        )
        lr = _log_returns(s)
        assert len(lr) == 2
        assert abs(lr.iloc[0] - np.log(110.0 / 100.0)) < 1e-9
        assert abs(lr.iloc[1] - np.log(105.0 / 110.0)) < 1e-9

    def test_rolling_corr_perfect(self):
        from bp_ingest.crypto_corr import _rolling_corr
        # y = 2x → 任意窗口 Pearson = 1.0
        idx = pd.bdate_range("2026-01-01", periods=20)
        x = pd.Series(np.arange(1.0, 21.0), index=idx)
        y = x * 2.0
        _dates, corr = _rolling_corr(x, y, 5, "pearson", idx)
        assert len(corr) == len(idx)
        valid = [v for v in corr if v is not None]
        assert len(valid) > 0
        assert all(abs(v - 1.0) < 1e-6 for v in valid)

    def test_rolling_corr_insufficient_window(self):
        from bp_ingest.crypto_corr import _rolling_corr
        idx = pd.bdate_range("2026-01-01", periods=3)
        x = pd.Series([1.0, 2.0, 3.0], index=idx)
        y = pd.Series([2.0, 4.0, 6.0], index=idx)
        dates, corr = _rolling_corr(x, y, 10, "pearson", idx)
        assert dates == [] and corr == []


class TestLoadCloseUsdNative:
    """`_load_close(usd_native=True)` 把 CNY 折算价还原成原生美元价 (/crypto 看板口径)。

    背景: 标普500 / 纳斯达克@global_index_em 的 currency 非 CNY, 清洗阶段已按日折算成
    人民币。若读侧直接读, /crypto 会把「人民币价」当成「美元价」展示(实测标普500 显示
    52643 而真实约 7799), 并让 BTC 的相关性偏离原生美元口径。这两条链路(组合回测走 CNY,
    /crypto 走 USD)必须各自自洽, 故此处固化还原除法。
    """

    D1 = date(2026, 9, 1)
    D2 = date(2026, 9, 30)

    def _conn(self, rows):
        from unittest.mock import MagicMock

        conn = MagicMock()
        cur = conn.cursor.return_value.__enter__.return_value
        cur.fetchall.return_value = rows
        return conn

    def _rows(self):
        # (trade_date, close, fill_flag, fx_rate)
        return [
            (date(2026, 9, 10), 70000.0, "real", 7.0),      # 折算价 → 10000 USD
            (date(2026, 9, 11), 70070.0, "real", 7.0),      # 折算价 → 10010 USD
            (date(2026, 9, 12), 70000.0, "interp", None),   # 插值行恒 NaN
        ]

    def test_usd_native_divides_out_fx_rate(self):
        from bp_ingest.crypto_corr import _load_close

        s = _load_close(self._conn(self._rows()), "标普500", "global_index_em",
                        self.D1, self.D2, usd_native=True)
        assert s.iloc[0] == pytest.approx(10000.0)
        assert s.iloc[1] == pytest.approx(10010.0)
        assert s.isna().sum() == 1          # interp 行仍置 NaN, 不受 usd_native 影响

    def test_default_keeps_cny_close(self):
        from bp_ingest.crypto_corr import _load_close

        s = _load_close(self._conn(self._rows()), "标普500", "global_index_em",
                        self.D1, self.D2)
        assert s.iloc[0] == pytest.approx(70000.0)   # 默认不还原(组合回测口径)

    def test_null_or_unit_fx_rate_is_not_divided(self):
        """BTC/DXY/COMEX 的 fx_rate 为 NULL 或 1 —— 还原除法绝不能把它们改掉。"""
        from bp_ingest.crypto_corr import _load_close

        rows = [
            (date(2026, 9, 10), 61000.0, "real", None),
            (date(2026, 9, 11), 61100.0, "real", 1.0),
        ]
        s = _load_close(self._conn(rows), "BTC-USD", "crypto_yfinance",
                        self.D1, self.D2, usd_native=True)
        assert s.iloc[0] == pytest.approx(61000.0)
        assert s.iloc[1] == pytest.approx(61100.0)

    def test_only_the_global_indices_use_usd_native(self):
        """只有被折算的两个全球指数走 usd_native, 且它们确实在面板里。"""
        import pathlib

        src = (pathlib.Path(__file__).resolve().parents[2]
               / "bp_ingest" / "crypto_corr.py").read_text(encoding="utf-8")
        # 还原调用点恰为标普500 / 纳斯达克两处(带右括号 = 实参, 不含文档里提到的名字)
        assert src.count("usd_native=True)") == 2
        assert src.count("usd_native: bool = False") == 1   # 默认不还原
        from bp_ingest import crypto_corr as cc

        assert cc.SP500_SYMBOL in cc.ALL_PANEL_SYMBOLS
        assert cc.NASDAQ_SYMBOL in cc.ALL_PANEL_SYMBOLS
