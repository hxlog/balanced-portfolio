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


def daily_expected_return(rets: pd.Series) -> float:
    """日收益率期望（算术平均）。"""
    return float(rets.mean()) if len(rets) > 0 else 0.0


def annualized_expected_return(rets: pd.Series, trading_days: int = DEFAULT_TRADING_DAYS) -> float:
    """年化期望 = 日均值 × 年交易日数。"""
    return float(rets.mean() * trading_days) if len(rets) > 0 else 0.0


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


def kurtosis_excess(rets: pd.Series) -> float:
    """超额峰度（excess kurtosis = 峰度 − 3）。"""
    n = len(rets)
    if n < 4:
        return 0.0
    m = rets.mean()
    s = rets.std(ddof=0)
    if s < 1e-12:
        return 0.0
    return float(((rets - m) ** 4).mean() / (s ** 4) - 3.0)


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
        "daily_expected_return": daily_expected_return(rets),
        "annualized_expected_return": annualized_expected_return(rets, trading_days),
        "skewness": skewness(rets),
        "kurtosis": kurtosis_excess(rets),
        "daily_return_median": median_return(rets),
    }
