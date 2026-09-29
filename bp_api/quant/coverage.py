"""成分行情覆盖判定 —— 「回测开始日期是否覆盖该标的」的**唯一事实源**。

为什么单独成模块: 这个判定必须与回测引擎的准入条件逐字一致, 否则 UI 会报出
引擎并不认可的风险(或漏报真实风险)。引擎的条件不是「有没有数据」, 而是
**「在滚动窗口 [max(1, end_idx-lookback+1), end_idx] 内攒够 min_window 个真实收盘日」**
(见 backtest.run_backtest 的 available_assets)。有数据但不足 min_window 的标的
同样拿不到权重 —— 用 first_clean_date > effective_start 近似会漏报这一类。

故把窗口数学(**union 日历**与**窗口内满员判定**)下沉到本模块, 由
backtest.py 反向 import —— 两处同源, 改一处即改另一处。本模块是纯函数,
不依赖 DB / settings, 便于单测直接构造面板。

面板约定(与 repositories.load_price_panel 一致):
  - index = 交易日(date), 列 = 资产 key(symbol@source);
  - 列内 NaN 表示该日不是该资产的**真实收盘日**(缺口/尚未上市/插值行);
    下市或停更造成的尾部缺口已由 load_price_panel 截断, 但成分之间仍可能不对称。
"""

from __future__ import annotations

from datetime import date
from typing import Optional

import numpy as np
import pandas as pd


def union_calendar(prices: pd.DataFrame) -> list:
    """各成分有效交易日的并集(排序)。"""
    all_dates: set = set()
    for col in prices.columns:
        all_dates.update(prices[col].dropna().index)
    return sorted(all_dates)


def window_bounds(end_idx: int, lookback: int) -> tuple[int, int]:
    """滚动窗口的闭区间下标 [a, b]。与 backtest._win_bounds 同源。"""
    return max(1, end_idx - lookback + 1), end_idx


def effective_min_window(min_window: int, lookback: int) -> int:
    """窗口实际长度 m = min(end_idx, lookback) <= lookback; 若 min_window > lookback,
    available 判定永远为空, 短窗口回测会一直报「数据不足」。故自动收紧。
    与 backtest.run_backtest 开头的两处收紧同源。"""
    if min_window < 2:
        min_window = 2
    if min_window > lookback:
        min_window = lookback
    return min_window


def available_at(
    assets: list[str],
    cum_valid: np.ndarray,
    end_idx: int,
    lookback: int,
    min_window: int,
) -> list[str]:
    """在 end_idx 这一天可参与优化的成分。

    与 backtest.available_assets 同源: 要求窗口长度 >= min_window, 且该成分在窗口内
    **每一个**交易日都是真实收盘(cum_valid 差值 == 窗口长度)。
    """
    if end_idx < 1:
        return []
    a, b = window_bounds(end_idx, lookback)
    m = b - a + 1
    if m < min_window:
        return []
    cnt = cum_valid[b] - (cum_valid[a - 1] if a > 0 else 0)
    return [asset for i, asset in enumerate(assets) if cnt[i] == m]


def cum_valid_counts(prices_aligned: pd.DataFrame) -> np.ndarray:
    """真实收盘日的累积计数 (T, n), 供窗口内满员判定做 O(1) 区间求和。"""
    return np.cumsum((~np.isnan(prices_aligned.values)).astype(np.int64), axis=0)


def compute_coverage(
    prices: pd.DataFrame,
    lookback: int,
    min_window: int,
    user_start: Optional[date] = None,
) -> dict:
    """算出每个成分的行情区间与「首次真正参与回测」的日期。

    返回:
        {
          "effective_start": date | None,   # 组合实际回测起点
          "assets": [
            {
              "key": "000300@cn_index_em",
              "first_date": date | None,        # 面板内首个真实收盘日
              "last_date": date | None,         # 末个真实收盘日
              "first_covered_date": date | None,# 首次拿到权重的交易日
              "covered_at_start": bool,         # 该成分在回测起点已参与
            }, ...
          ]
        }

    effective_start 与 backtest.run_backtest 的 k0 逻辑逐字对应:
    从 max(min_window+1, 用户 start 所在 index) 起, 找第一个「前一交易日已有
    至少一个成分满 min_window」的交易日 —— 决策只用 <= 前一日的数据, 故建仓日 t
    要求 t-1 已可优化。

    找不到这样的日子(可用历史不足)时 effective_start=None、covered_at_start 全 False,
    由调用方决定怎么呈现; 引擎自身在这条路径上会 raise, 本函数不 raise 以便
    /dashboard 与变更对话框能优雅降级。
    """
    if prices is None or prices.empty or len(prices.columns) == 0:
        return {"effective_start": None, "assets": []}

    assets = list(prices.columns)
    if lookback < 2:
        lookback = 2
    min_window = effective_min_window(min_window, lookback)

    price_dates = union_calendar(prices)
    if len(price_dates) < min_window + 2:
        # 历史不足以从任何一天开始 —— 引擎会 raise 「可用历史不足」, 这里降级返回。
        return {
            "effective_start": None,
            "assets": [
                {
                    "key": a,
                    "first_date": _first_valid(prices, a),
                    "last_date": _last_valid(prices, a),
                    "first_covered_date": None,
                    "covered_at_start": False,
                }
                for a in assets
            ],
        }

    prices_aligned = prices.reindex(price_dates)
    cum_valid = cum_valid_counts(prices_aligned)
    k_min = min_window + 1

    k_user = (
        next((k for k, d in enumerate(price_dates) if d >= user_start), k_min)
        if user_start is not None
        else 0
    )
    start_k = max(k_min, k_user)

    k0: Optional[int] = None
    for k in range(start_k, len(price_dates)):
        if available_at(assets, cum_valid, k - 1, lookback, min_window):
            k0 = k
            break

    effective_start = price_dates[k0] if k0 is not None else None

    # 每个成分「首次拿到权重」的日期: 引擎从 k_min 起逐日重算权重, 成分出现在
    # available_at(k-1) 的那天 k 就是它首次参与的日子。
    first_covered: dict[str, Optional[date]] = {a: None for a in assets}
    remaining = set(assets)
    for k in range(k_min, len(price_dates)):
        if not remaining:
            break
        for a in available_at(assets, cum_valid, k - 1, lookback, min_window):
            if a in remaining:
                first_covered[a] = price_dates[k]
                remaining.discard(a)

    return {
        "effective_start": effective_start,
        "assets": [
            {
                "key": a,
                "first_date": _first_valid(prices, a),
                "last_date": _last_valid(prices, a),
                "first_covered_date": first_covered[a],
                "covered_at_start": (
                    effective_start is not None
                    and first_covered[a] is not None
                    and first_covered[a] <= effective_start
                ),
            }
            for a in assets
        ],
    }


def _first_valid(prices: pd.DataFrame, col: str):
    v = prices[col].first_valid_index()
    return None if v is None else v


def _last_valid(prices: pd.DataFrame, col: str):
    v = prices[col].last_valid_index()
    return None if v is None else v
