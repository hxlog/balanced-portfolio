"""质量门：OHLC 合规、覆盖率、行数、交叉源一致性、hfq/bfq 比率漂移、新鲜度。

设计 §8。原则：任何不达标都必须落 bp_etl_quality_issue（可视化/可审计），
但"未追平"不终止流程（orchestrator 继续无限追赶）。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date
from typing import Iterable, Sequence

from bp_etl.adapters.base import Bar

DEFAULT_TOLERANCES = {"bfq": 0.001, "hfq": 0.003}  # 收盘差 / 收益率差


@dataclass(frozen=True)
class QualityIssue:
    dataset: str
    kind: str  # ohlc / coverage / row_delta / cross_source / ratio_drift / freshness / future
    severity: str  # info / warn / error
    symbol: str | None = None
    trade_date: date | None = None
    detail: dict = field(default_factory=dict)


@dataclass
class QualityReport:
    ok: bool
    coverage: float
    issues: list[QualityIssue] = field(default_factory=list)

    @property
    def errors(self) -> list[QualityIssue]:
        return [issue for issue in self.issues if issue.severity == "error"]


def sanitize_bars(
    dataset: str, bars: Sequence[Bar], *, today: date | None = None
) -> tuple[list[Bar], list[QualityIssue]]:
    """过滤非法行并记录 issue：OHLC 完整性、负量、未来日期。"""
    today = today or date.today()
    good: list[Bar] = []
    issues: list[QualityIssue] = []
    for bar in bars:
        reason: str | None = None
        if bar.trade_date > today:
            reason = "future_date"
        elif not bar.close or bar.close <= 0:
            reason = "close_non_positive"
        elif bar.volume is not None and bar.volume < 0:
            reason = "negative_volume"
        else:
            ohlc = [value for value in (bar.open, bar.high, bar.low) if value is not None]
            if bar.low is not None and bar.high is not None and bar.low > bar.high:
                reason = "low_gt_high"
            elif bar.low is not None and bar.low > bar.close:
                reason = "low_gt_close"
            elif bar.high is not None and bar.high < bar.close:
                reason = "high_lt_close"
            elif ohlc and min(ohlc) <= 0:
                reason = "non_positive_price"
        if reason is None:
            good.append(bar)
        else:
            issues.append(
                QualityIssue(
                    dataset=dataset, kind=reason, severity="error",
                    symbol=bar.symbol, trade_date=bar.trade_date,
                    detail={"close": bar.close, "open": bar.open, "high": bar.high, "low": bar.low},
                )
            )
    return good, issues


def evaluate(
    dataset: str,
    trade_date: date,
    adjust: str,
    bars: Sequence[Bar],
    expected_count: int,
    *,
    coverage_min: float,
    previous_count: int | None = None,
    row_delta_floor: float = 0.98,
) -> QualityReport:
    """单 (dataset, adjust) 单日覆盖率/行数门。bars 应已 sanitize。"""
    issues: list[QualityIssue] = []
    symbols = {bar.symbol for bar in bars if bar.trade_date == trade_date}
    coverage = (len(symbols) / expected_count) if expected_count > 0 else 0.0
    if expected_count > 0 and coverage < coverage_min:
        issues.append(
            QualityIssue(
                dataset=dataset, kind="coverage", severity="error", trade_date=trade_date,
                detail={"coverage": round(coverage, 4), "expected": expected_count, "got": len(symbols)},
            )
        )
    if previous_count and previous_count > 0:
        if len(symbols) < int(previous_count * row_delta_floor):
            issues.append(
                QualityIssue(
                    dataset=dataset, kind="row_delta", severity="warn", trade_date=trade_date,
                    detail={"previous": previous_count, "got": len(symbols), "adjust": adjust},
                )
            )
    last_dates = {bar.trade_date for bar in bars}
    if bars and trade_date not in last_dates:
        issues.append(
            QualityIssue(
                dataset=dataset, kind="freshness", severity="error", trade_date=trade_date,
                detail={"last_dates": sorted(str(d) for d in last_dates)[-3:]},
            )
        )
    ok = not any(issue.severity == "error" for issue in issues)
    return QualityReport(ok=ok, coverage=coverage, issues=issues)


def cross_source_issues(
    dataset: str,
    adjust: str,
    primary: Sequence[Bar],
    check: Sequence[Bar],
    *,
    tolerance_ratio: float | None = None,
) -> list[QualityIssue]:
    """双源同日收盘比对：bfq 差 ≤0.1%，hfq 用收益率差 ≤0.3%。"""
    tol = tolerance_ratio if tolerance_ratio is not None else DEFAULT_TOLERANCES.get(adjust, 0.003)
    primary_by_date = {bar.trade_date: bar.close for bar in primary if bar.close}
    check_by_date = {bar.trade_date: bar.close for bar in check if bar.close}
    dates = sorted(set(primary_by_date) & set(check_by_date))
    if len(dates) >= 2:
        # hfq 绝对价可能不同基准：用收益率比较
        ret_p = primary_by_date[dates[-1]] / primary_by_date[dates[-2]] - 1.0
        ret_c = check_by_date[dates[-1]] / check_by_date[dates[-2]] - 1.0
        if abs(ret_p - ret_c) > tol * 10:
            return [
                QualityIssue(
                    dataset=dataset, kind="cross_source", severity="warn",
                    trade_date=dates[-1],
                    detail={"primary_ret": ret_p, "check_ret": ret_c, "adjust": adjust},
                )
            ]
        return []
    for day in dates:
        base = check_by_date[day]
        if base and abs(primary_by_date[day] / base - 1.0) > tol:
            return [
                QualityIssue(
                    dataset=dataset, kind="cross_source", severity="warn", trade_date=day,
                    detail={"primary": primary_by_date[day], "check": base, "adjust": adjust},
                )
            ]
    return []


def ratio_drift_issues(
    dataset: str,
    symbol: str,
    bfq_bars: Sequence[Bar],
    hfq_bars: Sequence[Bar],
    *,
    max_change: float = 0.005,
) -> list[QualityIssue]:
    """hfq/bfq 比率除权日外应为常数；非除权日变化 >max_change 记 warn。

    注意：除权日比率变化属合法，故只记 warn 不记 error（由人工/下一轮校验）。
    """
    bfq = {bar.trade_date: bar.close for bar in bfq_bars if bar.close}
    hfq = {bar.trade_date: bar.close for bar in hfq_bars if bar.close}
    dates = sorted(set(bfq) & set(hfq))
    issues: list[QualityIssue] = []
    previous_ratio: float | None = None
    for day in dates:
        ratio = hfq[day] / bfq[day] if bfq[day] else None
        if ratio is None:
            continue
        if previous_ratio is not None and previous_ratio > 0:
            change = abs(ratio / previous_ratio - 1.0)
            if change > max_change:
                issues.append(
                    QualityIssue(
                        dataset=dataset, kind="ratio_drift", severity="warn",
                        symbol=symbol, trade_date=day,
                        detail={"previous_ratio": previous_ratio, "ratio": ratio, "change": change},
                    )
                )
        previous_ratio = ratio
    return issues
