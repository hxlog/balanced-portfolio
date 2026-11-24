"""verify 工具：Decimal/float 混算与比率漂移统计。"""
from __future__ import annotations

from decimal import Decimal

from bp_etl.verify import ratio_drift_stats


def test_ratio_drift_stats_accepts_decimal() -> None:
    stats = ratio_drift_stats([Decimal("6.74"), Decimal("6.74"), Decimal("6.80")])
    assert stats["points"] == 3
    assert stats["drift_count"] == 1
    assert stats["ok"] is False


def test_ratio_drift_stats_none_and_empty() -> None:
    stats = ratio_drift_stats([None, None])
    assert stats["points"] == 0 and stats["ok"] is True

def test_market_filter_distinguishes_a_and_hk() -> None:
    from bp_etl.registry import REGISTRY
    from bp_etl.verify import _market_filter

    assert _market_filter(REGISTRY["a_stock"]).strip() == "AND length(symbol)=6"
    assert _market_filter(REGISTRY["hk_stock"]).strip() == "AND length(symbol)=5"
    assert _market_filter(REGISTRY["etf"]) == ""
