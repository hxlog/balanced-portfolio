"""锚定与回退重锚：保证同一 (dataset, adjust) 序列只有一个绝对价格基准。

设计 §3/§8：
- 锚定源决定序列基准；回退源写入前按「最近 3 个重叠日收盘比的中位数」缩放 OHLC，
  收益率不变、绝对值对齐锚定基准；
- 无重叠日 → NoOverlapError（禁止猜基准写库）。
"""

from __future__ import annotations

import statistics
from typing import Sequence

from bp_etl.adapters.base import Bar

MAX_OVERLAP_DAYS = 3


class NoOverlapError(RuntimeError):
    """回退源与锚定源无重叠交易日，无法安全重锚。"""


def overlap_ratio(
    anchor_bars: Sequence[Bar],
    fallback_bars: Sequence[Bar],
) -> float:
    """最近 MAX_OVERLAP_DAYS 个重叠日的收盘比中位数（anchor / fallback）。"""
    anchor_by_date = {
        bar.trade_date: bar.close for bar in anchor_bars if bar.close and bar.close > 0
    }
    pairs: list[tuple[object, float, float]] = []
    for bar in fallback_bars:
        anchor_close = anchor_by_date.get(bar.trade_date)
        if not anchor_close or not bar.close or bar.close <= 0:
            continue
        pairs.append((bar.trade_date, bar.close, anchor_close))
    if not pairs:
        raise NoOverlapError("回退源与锚定源无重叠交易日")
    pairs.sort(key=lambda item: item[0])
    ratios = [anchor / fallback for _, fallback, anchor in pairs[-MAX_OVERLAP_DAYS:]]
    return statistics.median(ratios)


def reanchor(
    anchor_bars: Sequence[Bar],
    fallback_bars: Sequence[Bar],
) -> list[Bar]:
    """把回退源 bars 缩放到锚定基准；source 标记 `:anchored` 以保留审计。"""
    if not fallback_bars:
        return []
    ratio = overlap_ratio(anchor_bars, fallback_bars)
    fallback_source = fallback_bars[0].source or "fallback"
    anchored_source = f"{fallback_source}:anchored"
    out: list[Bar] = []
    for bar in fallback_bars:
        out.append(
            Bar(
                symbol=bar.symbol,
                trade_date=bar.trade_date,
                open=_scale(bar.open, ratio),
                high=_scale(bar.high, ratio),
                low=_scale(bar.low, ratio),
                close=bar.close * ratio,
                volume=bar.volume,
                amount=_scale(bar.amount, ratio),
                pct_change=bar.pct_change,
                source=anchored_source,
                adjust=bar.adjust,
            )
        )
    return out


def _scale(value: float | None, ratio: float) -> float | None:
    return None if value is None else value * ratio
