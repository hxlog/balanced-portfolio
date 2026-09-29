"""绩效指标与周期收益率/波动率。

输入: 单位净值序列(index=日期, 起点=1.0)。
输出: 适合落库为 JSONB 的指标字典。
"""

from __future__ import annotations

from datetime import date
from typing import Optional

import numpy as np
import pandas as pd

DEFAULT_TRADING_DAYS = 244
DEFAULT_RISK_FREE = 0.0

# 周期 → 交易日数(年初至今与年化单独处理)
PERIOD_WINDOWS = {
    "1d": 1,
    "1w": 5,
    "1m": 21,
    "3m": 63,
    "6m": 126,
    "1y": 244,
    "3y": 732,
}


def max_drawdown(nav: pd.Series) -> float:
    """最大回撤(负值)。"""
    roll_max = nav.cummax()
    dd = nav / roll_max - 1.0
    return float(dd.min())


def max_drawdown_recovery_days(nav: pd.Series) -> Optional[int]:
    """最大回撤修复交易日数: 从最大回撤谷底恢复至前高所需天数; 尚未修复返回 None。"""
    nav = nav.dropna()
    if len(nav) < 2:
        return None
    cummax = nav.cummax()
    dd = nav / cummax - 1.0
    trough_i = int(dd.values.argmin())
    if trough_i <= 0:
        return 0
    peak = float(cummax.iloc[trough_i])
    for j in range(trough_i + 1, len(nav)):
        if float(nav.iloc[j]) >= peak - 1e-12:
            return j - trough_i
    return None


def _annualized_return(nav: pd.Series, trading_days: int) -> float:
    n = len(nav) - 1
    if n <= 0:
        return 0.0
    total = nav.iloc[-1] / nav.iloc[0]
    if total <= 0:
        return -1.0
    return float(total ** (trading_days / n) - 1.0)


def _annualized_vol(rets: pd.Series, trading_days: int) -> float:
    return float(rets.std(ddof=1) * np.sqrt(trading_days)) if len(rets) > 1 else 0.0


def _downside_vol(rets: pd.Series, mar_daily: float, trading_days: int) -> float:
    downside = np.minimum(rets.values - mar_daily, 0.0)
    return float(np.sqrt(np.mean(downside**2)) * np.sqrt(trading_days))


def _period_return(nav: pd.Series, window: int) -> Optional[float]:
    if len(nav) <= window:
        return None
    return float(nav.iloc[-1] / nav.iloc[-1 - window] - 1.0)


def _period_vol(rets: pd.Series, window: int, trading_days: int) -> Optional[float]:
    if len(rets) < window or window < 2:
        return None
    return _annualized_vol(rets.iloc[-window:], trading_days)


def _ytd_return(nav: pd.Series) -> Optional[float]:
    if nav.empty:
        return None
    last_dt = pd.Timestamp(nav.index[-1])
    year_start = date(last_dt.year, 1, 1)
    # 取年初前最后一个净值作为基准(年初首个交易日的前收)
    base_idx = [d for d in nav.index if d < year_start]
    base = nav.loc[base_idx[-1]] if base_idx else nav.iloc[0]
    return float(nav.iloc[-1] / base - 1.0)


def _year_base(nav: pd.Series, year: int) -> float:
    """某年的收益基准净值: 该年首个交易日前一天的净值(年初前最后一个)。

    起始年没有「前一年末」净值时退化为该年首个净值 —— 此时区间收益率即该年内涨幅。
    """
    year_start = date(year, 1, 1)
    prior = [d for d in nav.index if d < year_start]
    return float(nav.loc[prior[-1]]) if prior else float(nav.iloc[0])


def annual_returns(nav: pd.Series, trading_days: int = DEFAULT_TRADING_DAYS) -> dict:
    """按自然年切分的收益率 + ytd(**全部折算年化**)。

    不完整年份(起始年、当年 YTD)**也折算年化**: 时长 <1 年时直接看累计涨幅会系统性
    偏低(只有 2 个月的数据自然只涨 2 个月的量), 折算后各列才横向可比。折算口径与
    `_annualized_return` 一致: growth^(trading_days/n) - 1, n 为该年内实际样本点数。

    注意与 `_ytd_return`(period_returns["ytd"], 「年初至今」的**累计**涨幅)语义不同 ——
    那是既有的滚动窗口列, 保持累计; 这里的 ytd 是年度表的一列, 与相邻年份同尺度。

    键: 'ytd' + 各年字符串('2025' 等), 年份倒序。
    """
    nav = nav.dropna()
    if nav.empty:
        return {}
    idx_years = [pd.Timestamp(d).year for d in nav.index]
    years = sorted(set(idx_years), reverse=True)
    if not years:
        return {}

    def _annualize(seg, base: float) -> float:
        if seg.empty:
            return 0.0
        growth = float(seg.iloc[-1] / base) if base > 0 else 0.0
        n = len(seg)
        # growth<=0 时幂运算会炸, 退化为累计涨幅(nav 归零的极端情形, 年化无意义)。
        return float(growth ** (trading_days / n) - 1.0) if n > 0 and growth > 0 else growth - 1.0

    out: dict[str, Optional[float]] = {}
    for y in years:
        seg = nav[[g == y for g in idx_years]]
        out[str(y)] = _annualize(seg, _year_base(nav, y))
    # ytd: 与「今年」那一列同段同基, 只是年份取末个样本所在年。
    this_year = years[0]
    out["ytd"] = _annualize(
        nav[[g == this_year for g in idx_years]], _year_base(nav, this_year)
    )
    return out


def annual_vols(nav: pd.Series, trading_days: int = DEFAULT_TRADING_DAYS) -> dict:
    """按自然年切分的波动率(年内日收益标准差 × √年交易日数)。

    取 nav 而非 rets 作为入参, 是为了让**键集与 `annual_returns` 完全一致**
    (年度表的行/列要对齐; 首年只有 1 个净值点时收益仍应有该列, 波动率显示为 None)。

    与现有 `_period_vol` 同尺度(恒年化), 便于与「区间波动率」横向对照。
    年内少于 2 个收益样本的年份返回 None。
    键: 'ytd' + 各年字符串; 不含 'annualized' —— 全区间年化由调用方从
    `annualized_vol` 直接取, 避免同一口径算两遍(且那是「全区间」不是「某一年」)。
    """
    nav = nav.dropna()
    if nav.empty:
        return {}
    rets = nav.pct_change().dropna()
    idx_years = [pd.Timestamp(d).year for d in nav.index]
    years = sorted(set(idx_years), reverse=True)
    if not years:
        return {}
    ret_years = [pd.Timestamp(d).year for d in rets.index]

    def _vol(y: int) -> Optional[float]:
        seg = rets[[g == y for g in ret_years]]
        return _annualized_vol(seg, trading_days) if len(seg) > 1 else None

    out: dict[str, Optional[float]] = {str(y): _vol(y) for y in years}
    out["ytd"] = _vol(years[0])
    return out


def daily_expected_return(rets: pd.Series) -> float:
    """日收益率期望（算术平均）。"""
    return float(rets.mean()) if len(rets) > 0 else 0.0


def annualized_expected_return(rets: pd.Series, trading_days: int = DEFAULT_TRADING_DAYS) -> float:
    """年化期望 = 日均值 × 年交易日数。"""
    return float(rets.mean() * trading_days) if len(rets) > 0 else 0.0


def daily_volatility(rets: pd.Series) -> float:
    """日波动率（日收益率标准差，ddof=1）。"""
    return float(rets.std(ddof=1)) if len(rets) > 1 else 0.0


def skewness(rets: pd.Series) -> float:
    """偏度（调整样本偏度）。"""
    n = len(rets)
    if n < 3:
        return 0.0
    m = rets.mean()
    s = rets.std(ddof=0)
    if s < 1e-12:
        return 0.0
    return float(((rets - m) ** 3).mean() / (s ** 3))


def bowley_skewness(rets: pd.Series) -> float:
    """Bowley 偏度 = (Q3 + Q1 − 2·Q2) / (Q3 − Q1)，基于四分位数的鲁棒偏度。"""
    if len(rets) < 3:
        return 0.0
    q1 = float(rets.quantile(0.25))
    q2 = float(rets.quantile(0.50))
    q3 = float(rets.quantile(0.75))
    denom = q3 - q1
    if abs(denom) < 1e-12:
        return 0.0
    return float((q3 + q1 - 2.0 * q2) / denom)


def kurtosis(rets: pd.Series) -> float:
    """峰度（Pearson 峰度，正态分布=3）。"""
    n = len(rets)
    if n < 4:
        return 0.0
    m = rets.mean()
    s = rets.std(ddof=0)
    if s < 1e-12:
        return 0.0
    return float(((rets - m) ** 4).mean() / (s ** 4))


def median_return(rets: pd.Series) -> float:
    """日收益率中位数。"""
    return float(rets.median()) if len(rets) > 0 else 0.0


def compute_metrics(
    nav: pd.Series,
    benchmark_nav: Optional[pd.Series] = None,
    risk_free: float = DEFAULT_RISK_FREE,
    trading_days: int = DEFAULT_TRADING_DAYS,
) -> dict:
    """计算单条净值序列的绩效 + 周期收益率/波动率。"""
    nav = nav.dropna()
    rets = nav.pct_change().dropna()
    rf_daily = risk_free / trading_days

    ann_ret = _annualized_return(nav, trading_days)
    ann_vol = _annualized_vol(rets, trading_days)
    dvol = _downside_vol(rets, rf_daily, trading_days)
    mdd = max_drawdown(nav)

    sharpe = (ann_ret - risk_free) / ann_vol if ann_vol > 1e-12 else 0.0
    sortino = (ann_ret - risk_free) / dvol if dvol > 1e-12 else 0.0
    calmar = ann_ret / abs(mdd) if mdd < -1e-12 else 0.0

    info_ratio = None
    if benchmark_nav is not None:
        bench = benchmark_nav.reindex(nav.index).dropna()
        common = rets.index.intersection(bench.pct_change().dropna().index)
        if len(common) > 1:
            excess = rets.loc[common] - bench.pct_change().dropna().loc[common]
            te = excess.std(ddof=1) * np.sqrt(trading_days)
            info_ratio = float(excess.mean() * trading_days / te) if te > 1e-12 else 0.0

    period_returns = {k: _period_return(nav, w) for k, w in PERIOD_WINDOWS.items()}
    period_returns["ytd"] = _ytd_return(nav)
    period_returns["annualized"] = ann_ret

    period_vols = {k: _period_vol(rets, w, trading_days) for k, w in PERIOD_WINDOWS.items()}
    period_vols["annualized"] = ann_vol

    # 年度表(自然年 + YTD + 全区间年化)。'annualized' 直接复用上面已算好的值,
    # 前端据此把该列与「区间收益率与波动率」表的 annualized 列对齐(同一个数)。
    ann_ret_map = annual_returns(nav, trading_days)
    ann_ret_map["annualized"] = ann_ret
    ann_vol_map = annual_vols(nav, trading_days)
    ann_vol_map["annualized"] = ann_vol

    return {
        "annualized_return": ann_ret,
        "annualized_vol": ann_vol,
        "sharpe": sharpe,
        "sortino": sortino,
        "calmar": calmar,
        "max_drawdown": mdd,
        "max_drawdown_recovery_days": max_drawdown_recovery_days(nav),
        "information_ratio": info_ratio,
        "total_return": float(nav.iloc[-1] / nav.iloc[0] - 1.0) if len(nav) > 1 else 0.0,
        "start_date": str(nav.index[0]),
        "end_date": str(nav.index[-1]),
        "period_returns": period_returns,
        "period_vols": period_vols,
        "annual_returns": ann_ret_map,
        "annual_vols": ann_vol_map,
        "daily_expected_return": daily_expected_return(rets),
        "annualized_expected_return": annualized_expected_return(rets, trading_days),
        "daily_volatility": daily_volatility(rets),
        "skewness": skewness(rets),
        "bowley_skewness": bowley_skewness(rets),
        "kurtosis": kurtosis(rets),
        "daily_return_median": median_return(rets),
    }
