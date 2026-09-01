"""多源聚合降级与逻辑源分组的单元测试。"""

from __future__ import annotations

from datetime import date

import pandas as pd
import pytest

from bp_ingest import sources as src


def _df(dates, closes):
    return pd.DataFrame(
        {
            "trade_date": dates,
            "open": closes,
            "high": closes,
            "low": closes,
            "close": closes,
            "volume": [100] * len(dates),
            "amount": [None] * len(dates),
            "turnover_rate": [None] * len(dates),
            "pct_change": [None] * len(dates),
        }
    )


def test_align_fallback_scales_to_base_close():
    """降级源按重叠日收盘比值重锚到主源口径(腾讯 hfq 单位净值 → 东财 hfq 价格)。"""
    base = _df([date(2026, 8, 1), date(2026, 8, 2)], [100.0, 101.0])
    fb = _df([date(2026, 8, 1), date(2026, 8, 2), date(2026, 8, 3)], [1.0, 1.01, 1.02])
    aligned = src._align_fallback_to_base(base, fb)
    # 重叠日(08-02) 101/1.01 = 100 → 08-03 close 1.02*100 = 102.0
    assert aligned[aligned["trade_date"] == date(2026, 8, 3)]["close"].iloc[0] == pytest.approx(102.0)


def test_align_fallback_uses_anchor_close_when_no_overlap():
    """主源整段失败、无重叠时, 用库中锚点 close 对齐降级源。"""
    fb = _df([date(2026, 8, 3), date(2026, 8, 4)], [1.09, 1.10])
    aligned = src._align_fallback_to_base(None, fb, anchor_close=109.0, anchor_date=date(2026, 8, 3))
    assert aligned[aligned["trade_date"] == date(2026, 8, 3)]["close"].iloc[0] == pytest.approx(109.0)
    assert aligned[aligned["trade_date"] == date(2026, 8, 4)]["close"].iloc[0] == pytest.approx(110.0)


def test_align_fallback_noop_when_ratio_one():
    fb = _df([date(2026, 8, 3)], [50.0])
    aligned = src._align_fallback_to_base(None, fb, anchor_close=50.0, anchor_date=date(2026, 8, 3))
    assert aligned[aligned["trade_date"] == date(2026, 8, 3)]["close"].iloc[0] == pytest.approx(50.0)


def test_tx_market_prefix():
    assert src._tx_market_prefix("510300") == "sh510300"
    assert src._tx_market_prefix("159915") == "sz159915"
    assert src._tx_market_prefix("sh000300") == "sh000300"


def test_aggregate_chains_include_tencent_etf_fallback():
    """东财 ETF 主源应降级腾讯(后复权), 不再降级新浪(无复权)。"""
    assert src.AGGREGATE_CHAINS["etf_em"] == ["etf_tx"]
    assert "etf_sina" not in src.AGGREGATE_CHAINS.get("etf_em", [])
    assert "index_tx" in src.AGGREGATE_CHAINS["cn_index_em"]
