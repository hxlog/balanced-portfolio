#!/usr/bin/env python3
"""每日 09:30 全站数据体检（8 类数据）：覆盖率 / 时效 / 准确性 + 落库 + 告警。

背景（2026-11-27 第二轮反馈）
-----------------------------
用户要求「每天 09:30 出体检报告，异常写 bp_etl_quality_issue」；阈值参考
docs/superpowers/specs/2026-11-23-unified-market-etl-design.md §8 与
docs/design/2026-11-27-unified-redesign/data-timeliness-plan.md §5：
- A 股 ≥0.995、ETF ≥0.96、港股 ≥0.97、基金 ≥0.90（与 bp_etl.registry 同口径）；
- 跟踪指数行情 ≥0.99、指数估值 ≥0.99、MVI 最新周有值、CFFEX 当日有值；
- 近 5 年每年交易日覆盖 ≥99.5%（≈242/243）；
- clean 与 raw 最大日期差 ≤0 天；跨源 PE 相对偏差 <5%；backlog < 1000；
- OHLC 非法行占比 / 收益跳变 / 指数跨源收盘差 作为准确性告警（warn）。

输出 / 落库
-----------
- 逐条检查写 bp_data_audit_daily(dataset, stat_date, metric, value, threshold,
  status, detail)，由 GET /api/v1/market/data-health 只读消费；
- 非 ok 的检查写 bp_etl_quality_issue（kind=audit:<metric>），管理端 data-health
  issues 可见；
- stdout 恒输出 JSON 报告；--output 可额外落文件；存在 error 时 exit 1（cron 告警）。

用法
----
    python scripts/daily_data_audit.py                  # 体检最近交易日并落库
    python scripts/daily_data_audit.py --dry-run         # 只输出报告不写库
    python scripts/daily_data_audit.py --date 2026-11-27 --output /tmp/audit.json
"""

from __future__ import annotations

import argparse
import json
import logging
import os
import sys
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta, timezone
from typing import Any, Mapping, Optional, Sequence

# 直接执行 python scripts/daily_data_audit.py 时 sys.path[0] 是 scripts/，
# 补上仓库根目录以便 import bp_etl / bp_ingest（cron 从任意 cwd 启动都能跑）。
_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)

from bp_etl.quality import QualityIssue  # noqa: E402
from bp_etl.registry import REGISTRY  # noqa: E402

logger = logging.getLogger("daily_data_audit")
CN = timezone(timedelta(hours=8))

#: 覆盖率阈值（v3 类直接取 registry.coverage_min，保证与 ETL 门控同口径）。
COVERAGE_THRESHOLDS: dict[str, float] = {
    "a_stock": REGISTRY["a_stock"].coverage_min,
    "hk_stock": REGISTRY["hk_stock"].coverage_min,
    "etf": REGISTRY["etf"].coverage_min,
    "fund_nav": REGISTRY["fund_nav"].coverage_min,
    "index_quotes": 0.99,
    "index_valuation": 0.99,
}
#: 8 类数据（顺序固定：a_stock/hk_stock/etf/fund_nav/cffex/index_quotes/index_valuation/mvi）。
AUDIT_DATASETS = (
    "a_stock", "hk_stock", "etf", "fund_nav",
    "cffex", "index_quotes", "index_valuation", "mvi",
)
#: 近 N 年每年交易日覆盖检查（用户要求 ≥99.5%，≈242/243）。
TRADING_YEARS = 5
MIN_TRADING_DAYS_PER_YEAR = 242
#: clean/组合清洗最大允许滞后（自然日，要求 0）。
CLEAN_RAW_MAX_LAG_DAYS = 0
#: 跨源 PE（csindex_value vs pingan_index）最大相对偏差与回看窗口。
PE_CROSS_SOURCE_MAX_REL_DIFF = 0.05
PE_CROSS_SOURCE_WINDOW_DAYS = 30
#: MVI 允许的最大滞后（自然日）：周频序列，最新周有值即可。
MVI_MAX_AGE_DAYS = 10
#: backlog 上限。
BACKLOG_MAX = 1000
#: 准确性阈值：单日收益跳变（百分点）与 OHLC 非法行占比、指数跨源收盘差对数。
RETURN_JUMP_PCT: dict[str, float] = {
    "a_stock": 20.0, "hk_stock": 30.0, "etf": 20.0, "index_quotes": 15.0,
}
OHLC_BAD_RATIO_MAX = 0.05
INDEX_CROSS_SOURCE_MAX_BAD_PAIRS = 10
#: 准确性表映射：(table, key_column, symbol_length filter or None, adjust)
ACCURACY_TABLES: dict[str, tuple[str, str, Optional[int], str]] = {
    "a_stock": ("bp_stock_quote_daily", "symbol", 6, "bfq"),
    "hk_stock": ("bp_stock_quote_daily", "symbol", 5, "bfq"),
    "etf": ("bp_etf_quote_daily", "etf_code", None, "bfq"),
    "index_quotes": ("bp_index_quote_daily", "symbol", None, "bfq"),
}


@dataclass
class AuditCheck:
    dataset: str
    metric: str
    value: Optional[float]
    threshold: Optional[float]
    status: str  # ok / warn / error
    detail: dict[str, Any] = field(default_factory=dict)

    @property
    def ok(self) -> bool:
        return self.status == "ok"

    def as_row(self, stat_date: date) -> tuple:
        return (
            self.dataset,
            stat_date,
            self.metric,
            self.value,
            self.threshold,
            self.status,
            json.dumps(self.detail, ensure_ascii=False, default=str),
        )


def make_check(
    dataset: str,
    metric: str,
    value: Optional[float],
    threshold: Optional[float],
    *,
    rule: str = "min",  # min=越大越好；max=越小越好
    severity: str = "error",  # 不达标时记 error 还是 warn
    detail: Optional[dict[str, Any]] = None,
) -> AuditCheck:
    """构造一条检查：value 为 None 或越界 -> error/warn。"""
    payload = dict(detail or {})
    if value is None:
        return AuditCheck(dataset, metric, None, threshold,
                          "error" if severity == "error" else "warn", payload)
    try:
        number = float(value)
    except (TypeError, ValueError):
        return AuditCheck(dataset, metric, None, threshold,
                          "error" if severity == "error" else "warn", payload)
    if threshold is None:
        status = "ok"
    else:
        ok = number >= float(threshold) if rule == "min" else number <= float(threshold)
        status = "ok" if ok else severity
    return AuditCheck(dataset, metric, number, threshold, status, payload)


# ---------------------------------------------------------------------------
# 只读查询助手（可 monkeypatch，便于纯 mock 单测）
# ---------------------------------------------------------------------------
def _fetchone(conn: Any, sql: str, params: Sequence[Any] = ()) -> Any:
    with conn.cursor() as cur:
        cur.execute(sql, tuple(params))
        return cur.fetchone()


def _fetchall(conn: Any, sql: str, params: Sequence[Any] = ()) -> list:
    with conn.cursor() as cur:
        cur.execute(sql, tuple(params))
        return list(cur.fetchall())


def expected_trade_date(conn: Any, reference: date) -> Optional[date]:
    """<= reference 的最近 A 股交易日（交易日历）。"""
    row = _fetchone(
        conn,
        "SELECT max(cal_date) FROM bp_trading_calendar"
        " WHERE market = 'CN' AND is_trading AND cal_date <= %s",
        (reference,),
    )
    return row[0] if row and row[0] is not None else None


def _lag_trading_days(conn: Any, as_of: Optional[date], expected: Optional[date]) -> Optional[int]:
    """as_of 到 expected 之间的交易日数（as_of 为空/超前时返回 None/0）。"""
    if as_of is None or expected is None or as_of >= expected:
        return 0 if as_of is not None and expected is not None else None
    row = _fetchone(
        conn,
        "SELECT count(*) FROM bp_trading_calendar"
        " WHERE market = 'CN' AND is_trading AND cal_date > %s AND cal_date <= %s",
        (as_of, expected),
    )
    return int(row[0] or 0) if row else None


def load_dataset_state(conn: Any, dataset: str, adjust: str) -> Optional[date]:
    row = _fetchone(
        conn,
        "SELECT last_success_date FROM bp_etl_dataset_state"
        " WHERE dataset = %s AND adjust = %s",
        (dataset, adjust),
    )
    return row[0] if row and row[0] is not None else None


def load_latest_run_coverage(conn: Any, dataset: str, adjust: str) -> tuple[Optional[float], Optional[date]]:
    row = _fetchone(
        conn,
        # bp_etl_run 没有 adjust 列（adjust 记录在 detail JSONB 内），
        # 审计按 detail->>'adjust' 过滤，避免 UndefinedColumn。
        "SELECT achieved_coverage, trade_date FROM bp_etl_run"
        " WHERE dataset = %s AND COALESCE(detail->>'adjust', '') = %s"
        " ORDER BY run_id DESC LIMIT 1",
        (dataset, adjust),
    )
    if not row:
        return None, None
    coverage = float(row[0]) if row[0] is not None else None
    return coverage, row[1]


TABLE_BY_DATASET: dict[str, tuple[str, str, Optional[str]]] = {
    # dataset -> (table, key_column, adjust 过滤; None = 无 adjust 维度)
    "a_stock": ("bp_stock_quote_daily", "symbol", "adjust"),
    "hk_stock": ("bp_stock_quote_daily", "symbol", "adjust"),
    "etf": ("bp_etf_quote_daily", "etf_code", "adjust"),
    "fund_nav": ("bp_fund_nav_daily", "fund_code", None),
}


def load_raw_max(conn: Any, dataset: str, adjust: str) -> Optional[date]:
    table, key, adjust_col = TABLE_BY_DATASET[dataset]
    if adjust_col:
        row = _fetchone(
            conn, f"SELECT max(trade_date) FROM {table} WHERE adjust = %s", (adjust,)
        )
    else:
        row = _fetchone(conn, f"SELECT max(trade_date) FROM {table}")
    return row[0] if row and row[0] is not None else None


def load_prev_day_ratio(conn: Any, dataset: str, adjust: str, expected: date) -> Optional[float]:
    """无 bp_etl_run 覆盖时的兜底：当日行数 / 上一交易日行数。"""
    table, key, adjust_col = TABLE_BY_DATASET[dataset]
    if adjust_col:
        today_row = _fetchone(
            conn,
            f"SELECT count(DISTINCT {key}) FROM {table}"
            " WHERE adjust = %s AND trade_date = %s",
            (adjust, expected),
        )
        prev_row = _fetchone(
            conn,
            f"SELECT count(DISTINCT {key}) FROM {table}"
            " WHERE adjust = %s AND trade_date = ("
            f" SELECT max(trade_date) FROM {table} WHERE adjust = %s AND trade_date < %s)",
            (adjust, adjust, expected),
        )
    else:
        today_row = _fetchone(
            conn,
            f"SELECT count(DISTINCT {key}) FROM {table} WHERE trade_date = %s",
            (expected,),
        )
        prev_row = _fetchone(
            conn,
            f"SELECT count(DISTINCT {key}) FROM {table} WHERE trade_date = ("
            f" SELECT max(trade_date) FROM {table} WHERE trade_date < %s)",
            (expected,),
        )
    today_count = int(today_row[0] or 0) if today_row else 0
    prev_count = int(prev_row[0] or 0) if prev_row else 0
    if prev_count <= 0:
        return None
    return today_count / prev_count


#: 免费源可覆盖的 tracked 指数市场（US/GLOBAL 无免费日 K 源，不计入分母，单独记录限制）。
FREE_INDEX_MARKETS: tuple[str, ...] = ("CSI", "SH", "SZ", "HK")


def load_index_quotes(conn: Any, expected: date) -> dict[str, Any]:
    total_row = _fetchone(
        conn,
        "SELECT count(*) FROM bp_index_master"
        " WHERE is_tracked = TRUE AND market = ANY(%s)",
        (list(FREE_INDEX_MARKETS),),
    )
    total = int(total_row[0] or 0) if total_row else 0
    covered_row = _fetchone(
        conn,
        "SELECT count(DISTINCT q.symbol) FROM bp_index_quote_daily q"
        " JOIN bp_index_master m ON m.index_code = q.symbol AND m.is_tracked = TRUE"
        " WHERE q.adjust = 'bfq' AND q.trade_date = %s AND m.market = ANY(%s)",
        (expected, list(FREE_INDEX_MARKETS)),
    )
    covered = int(covered_row[0] or 0) if covered_row else 0
    as_of_row = _fetchone(
        conn,
        "SELECT max(q.trade_date) FROM bp_index_quote_daily q"
        " JOIN bp_index_master m ON m.index_code = q.symbol AND m.is_tracked = TRUE"
        " WHERE q.adjust = 'bfq' AND q.trade_date >= current_date - 800"
        " AND m.market = ANY(%s)",
        (list(FREE_INDEX_MARKETS),),
    )
    as_of = as_of_row[0] if as_of_row and as_of_row[0] is not None else None
    return {"total": total, "covered": covered, "as_of": as_of}


def load_index_valuation(conn: Any, expected: date) -> dict[str, Any]:
    total_row = _fetchone(
        conn, "SELECT count(*) FROM bp_index_master WHERE is_tracked = TRUE"
    )
    total = int(total_row[0] or 0) if total_row else 0
    as_of_row = _fetchone(
        conn,
        "SELECT max(trade_date) FROM bp_index_valuation_daily"
        " WHERE is_primary AND trade_date <= %s",
        (expected,),
    )
    as_of = as_of_row[0] if as_of_row and as_of_row[0] is not None else None
    covered = 0
    if as_of is not None:
        covered_row = _fetchone(
            conn,
            "SELECT count(DISTINCT index_code) FROM bp_index_valuation_daily"
            " WHERE is_primary AND trade_date = %s",
            (as_of,),
        )
        covered = int(covered_row[0] or 0) if covered_row else 0
    return {"total": total, "covered": covered, "as_of": as_of}


def load_table_max(conn: Any, sql: str) -> Optional[date]:
    row = _fetchone(conn, sql)
    return row[0] if row and row[0] is not None else None


def load_clean_raw_lag(conn: Any) -> dict[str, Any]:
    clean_max = load_table_max(conn, "SELECT max(trade_date) FROM bp_quote_clean")
    raw_max = load_table_max(
        conn,
        "SELECT max(trade_date) FROM ("
        " SELECT max(trade_date) AS trade_date FROM bp_stock_quote_daily WHERE adjust = 'bfq'"
        " UNION ALL SELECT max(trade_date) FROM bp_etf_quote_daily WHERE adjust = 'bfq'"
        " UNION ALL SELECT max(trade_date) FROM bp_index_quote_daily WHERE adjust = 'bfq'"
        ") t",
    )
    lag = (
        max(0, (raw_max - clean_max).days)
        if raw_max is not None and clean_max is not None
        else None
    )
    return {"clean_max": clean_max, "raw_max": raw_max, "lag_days": lag}


def load_trading_year_coverage(conn: Any, years: int = TRADING_YEARS) -> list[dict[str, Any]]:
    start = date(date.today().year - years + 1, 1, 1)
    rows = _fetchall(
        conn,
        "SELECT extract(year FROM trade_date)::int, count(DISTINCT trade_date)"
        " FROM bp_quote_clean WHERE trade_date >= %s GROUP BY 1 ORDER BY 1",
        (start,),
    )
    actual = {int(row[0]): int(row[1] or 0) for row in rows}
    cal_rows = _fetchall(
        conn,
        "SELECT extract(year FROM cal_date)::int, count(*)"
        " FROM bp_trading_calendar"
        " WHERE market = 'CN' AND is_trading AND cal_date >= %s"
        " GROUP BY 1 ORDER BY 1",
        (start,),
    )
    calendar = {int(row[0]): int(row[1] or 0) for row in cal_rows}
    out: list[dict[str, Any]] = []
    for year in range(start.year, date.today().year + 1):
        out.append(
            {
                "year": year,
                "trading_days": actual.get(year, 0),
                "calendar_days": calendar.get(year, 0),
            }
        )
    return out


def load_accuracy(
    conn: Any,
    dataset: str,
    expected: date,
) -> Optional[dict[str, Any]]:
    """单表当日准确性：OHLC 非法行占比 + 收益跳变占比（fund_nav 只查净值<=0）。"""
    table_key = ACCURACY_TABLES.get(dataset)
    if table_key is None:
        return None
    table, key, symbol_length, adjust = table_key
    where = "trade_date = %s AND adjust = %s"
    params: list[Any] = [expected, adjust]
    if symbol_length is not None:
        where += f" AND length({key}) = %s"
        params.append(symbol_length)
    total_row = _fetchone(conn, f"SELECT count(*) FROM {table} WHERE {where}", params)
    total = int(total_row[0] or 0) if total_row else 0
    if total <= 0:
        return {"total": 0, "ohlc_bad": 0, "jump": 0}
    ohlc_row = _fetchone(
        conn,
        f"SELECT count(*) FROM {table} WHERE {where} AND (close IS NULL OR close <= 0"
        " OR (low IS NOT NULL AND high IS NOT NULL AND low > high)"
        " OR (low IS NOT NULL AND close IS NOT NULL AND low > close)"
        " OR (high IS NOT NULL AND close IS NOT NULL AND high < close)"
        " OR (open IS NOT NULL AND open <= 0))",
        params,
    )
    jump_pct = RETURN_JUMP_PCT.get(dataset)
    jump = 0
    if jump_pct is not None:
        jump_row = _fetchone(
            conn,
            f"SELECT count(*) FROM {table} WHERE {where}"
            " AND pct_change IS NOT NULL AND abs(pct_change) > %s",
            [*params, jump_pct],
        )
        jump = int(jump_row[0] or 0) if jump_row else 0
    return {
        "total": total,
        "ohlc_bad": int(ohlc_row[0] or 0) if ohlc_row else 0,
        "jump": jump,
        "jump_threshold_pct": jump_pct,
    }


def load_index_cross_source_bad_pairs(conn: Any, expected: date) -> int:
    row = _fetchone(
        conn,
        "SELECT count(*) FROM ("
        " SELECT symbol, max(close) AS hi, min(close) AS lo, count(DISTINCT source) AS n"
        " FROM bp_index_quote_daily"
        " WHERE adjust = 'bfq' AND trade_date = %s AND close IS NOT NULL"
        " GROUP BY symbol HAVING count(DISTINCT source) >= 2"
        ") t WHERE t.lo > 0 AND t.hi / t.lo - 1.0 > 0.001",
        (expected,),
    )
    return int(row[0] or 0) if row else 0


def load_pe_cross_source(conn: Any) -> dict[str, Any]:
    """csindex_value 与 pingan_index 同日 PE 最大相对偏差（近 30 天）。"""
    row = _fetchone(
        conn,
        "SELECT max(abs(s.value - p.value) / p.value), count(*)"
        " FROM bp_index_valuation_series s"
        " JOIN bp_index_valuation_series p"
        "   ON p.index_code = s.index_code AND p.trade_date = s.trade_date"
        "  AND p.metric = 'pe_ttm' AND p.calc_src = 'pingan_index'"
        " WHERE s.calc_src = 'csindex_value' AND s.metric = 'pe_ttm'"
        "   AND p.value > 0 AND s.value IS NOT NULL"
        "   AND s.trade_date >= current_date - %s",
        (PE_CROSS_SOURCE_WINDOW_DAYS,),
    )
    if not row or row[0] is None:
        return {"max_rel_diff": None, "samples": 0}
    return {"max_rel_diff": float(row[0]), "samples": int(row[1] or 0)}


def load_backlog_total(conn: Any) -> int:
    row = _fetchone(conn, "SELECT count(*) FROM bp_etl_backlog")
    return int(row[0] or 0) if row else 0


def load_freshness(conn: Any) -> dict[str, Any]:
    """复用 bp_data_freshness 读侧：报告里附带 8 类数据 as_of/status/source（可审计）。"""
    try:
        from bp_api.freshness import load_stored_rows  # noqa: PLC0415

        stored = load_stored_rows(conn)
    except Exception:  # noqa: BLE001 - freshness 表缺失/迁移未应用时不影响体检
        return {}
    out: dict[str, Any] = {}
    for key, row in stored.items():
        out[key] = {
            "as_of": row.get("as_of"),
            "status": row.get("status"),
            "source": row.get("source"),
        }
    return out


# ---------------------------------------------------------------------------
# 体检编排（纯计算 + 只读查询；写库在 persist）
# ---------------------------------------------------------------------------
def audit(conn: Any, reference: Optional[date] = None) -> dict[str, Any]:
    """执行全部检查，返回可序列化报告（不写库）。"""
    reference = reference or date.today()
    expected = expected_trade_date(conn, reference) or reference
    checks: list[AuditCheck] = []

    # 1) v3 四类（A 股/港股/ETF/基金）：as_of 时效 + 覆盖率
    for dataset, adjust in (
        ("a_stock", "bfq"), ("a_stock", "hfq"),
        ("hk_stock", "bfq"), ("hk_stock", "hfq"),
        ("etf", "bfq"), ("etf", "hfq"),
        ("fund_nav", "nav"),
    ):
        state_as_of = load_dataset_state(conn, dataset, adjust)
        raw_as_of = load_raw_max(conn, dataset, adjust)
        as_of = max([day for day in (state_as_of, raw_as_of) if day is not None], default=None)
        coverage, run_date = load_latest_run_coverage(conn, dataset, adjust)
        if coverage is None:
            coverage = load_prev_day_ratio(conn, dataset, adjust, expected)
        checks.append(
            make_check(
                dataset, f"as_of_lag_trading_days[{adjust}]",
                _lag_trading_days(conn, as_of, expected), 0, rule="max",
                severity="error",
                detail={"as_of": as_of.isoformat() if as_of else None,
                        "expected_date": expected.isoformat(),
                        "state_as_of": state_as_of.isoformat() if state_as_of else None},
            )
        )
        checks.append(
            make_check(
                dataset, f"coverage[{adjust}]", coverage,
                COVERAGE_THRESHOLDS[dataset], severity="error",
                detail={"run_trade_date": run_date.isoformat() if run_date else None},
            )
        )

    # 2) CFFEX：当日有值（时效）
    cffex_as_of = load_table_max(conn, "SELECT max(trade_date) FROM bp_cffex_contract_daily")
    checks.append(
        make_check(
            "cffex", "as_of_lag_trading_days",
            _lag_trading_days(conn, cffex_as_of, expected), 0, rule="max",
            severity="error",
            detail={"as_of": cffex_as_of.isoformat() if cffex_as_of else None,
                    "expected_date": expected.isoformat()},
        )
    )

    # 3) 指数行情：覆盖率 + 时效
    index_quotes = load_index_quotes(conn, expected)
    total_iq = index_quotes["total"] or 0
    ratio_iq = (index_quotes["covered"] / total_iq) if total_iq else None
    checks.append(
        make_check(
            "index_quotes", "coverage", ratio_iq, COVERAGE_THRESHOLDS["index_quotes"],
            severity="error",
            detail={"covered": index_quotes["covered"], "total": total_iq},
        )
    )
    checks.append(
        make_check(
            "index_quotes", "as_of_lag_trading_days",
            _lag_trading_days(conn, index_quotes["as_of"], expected), 0,
            rule="max", severity="error",
            detail={"as_of": index_quotes["as_of"].isoformat() if index_quotes["as_of"] else None,
                    "expected_date": expected.isoformat()},
        )
    )

    # 4) 指数估值：覆盖率 + 时效
    valuation = load_index_valuation(conn, expected)
    total_iv = valuation["total"] or 0
    ratio_iv = (valuation["covered"] / total_iv) if total_iv else None
    checks.append(
        make_check(
            "index_valuation", "coverage", ratio_iv, COVERAGE_THRESHOLDS["index_valuation"],
            severity="error",
            detail={"covered": valuation["covered"], "total": total_iv},
        )
    )
    checks.append(
        make_check(
            "index_valuation", "as_of_lag_trading_days",
            _lag_trading_days(conn, valuation["as_of"], expected), 0,
            rule="max", severity="error",
            detail={"as_of": valuation["as_of"].isoformat() if valuation["as_of"] else None,
                    "expected_date": expected.isoformat()},
        )
    )

    # 5) MVI：最新周有值（自然日滞后 <= MVI_MAX_AGE_DAYS）
    mvi_as_of = load_table_max(conn, "SELECT max(as_of) FROM bp_market_valuation_index")
    mvi_lag = (
        max(0, (expected - mvi_as_of).days) if mvi_as_of is not None else None
    )
    checks.append(
        make_check(
            "mvi", "as_of_lag_days", mvi_lag, MVI_MAX_AGE_DAYS, rule="max",
            severity="error",
            detail={"as_of": mvi_as_of.isoformat() if mvi_as_of else None,
                    "expected_date": expected.isoformat()},
        )
    )

    # 6) clean vs raw 最大日期差（自然日）
    clean_raw = load_clean_raw_lag(conn)
    checks.append(
        make_check(
            "clean", "clean_raw_lag_days", clean_raw["lag_days"],
            CLEAN_RAW_MAX_LAG_DAYS, rule="max", severity="error",
            detail={"clean_max": clean_raw["clean_max"].isoformat() if clean_raw["clean_max"] else None,
                    "raw_max": clean_raw["raw_max"].isoformat() if clean_raw["raw_max"] else None},
        )
    )

    # 7) 近 5 年每年交易日覆盖
    for item in load_trading_year_coverage(conn):
        checks.append(
            make_check(
                "clean", f"trading_days_{item['year']}", item["trading_days"],
                MIN_TRADING_DAYS_PER_YEAR, severity="error",
                detail={"calendar_days": item["calendar_days"],
                        "min_ratio": 0.995},
            )
        )

    # 8) 准确性：OHLC / 收益跳变 / 指数跨源
    for dataset in ("a_stock", "hk_stock", "etf", "index_quotes"):
        accuracy = load_accuracy(conn, dataset, expected)
        if accuracy is None:
            continue
        total = accuracy["total"]
        ohlc_ratio = (accuracy["ohlc_bad"] / total) if total else None
        checks.append(
            make_check(
                dataset, "ohlc_bad_ratio", ohlc_ratio, OHLC_BAD_RATIO_MAX,
                rule="max", severity="warn",
                detail={"bad_rows": accuracy["ohlc_bad"], "rows": total},
            )
        )
        jump_ratio = (accuracy["jump"] / total) if total else None
        checks.append(
            make_check(
                dataset, "return_jump_ratio", jump_ratio, 0.005,
                rule="max", severity="warn",
                detail={"jump_rows": accuracy["jump"], "rows": total,
                        "jump_threshold_pct": accuracy.get("jump_threshold_pct")},
            )
        )
    bad_pairs = load_index_cross_source_bad_pairs(conn, expected)
    checks.append(
        make_check(
            "index_quotes", "cross_source_bad_pairs", bad_pairs,
            INDEX_CROSS_SOURCE_MAX_BAD_PAIRS, rule="max", severity="warn",
            detail={"rule": "同(指数,日)多源收盘相对差 > 0.1% 的对数"},
        )
    )

    # 9) 跨源 PE 偏差（csindex_value vs pingan_index）
    pe_cross = load_pe_cross_source(conn)
    checks.append(
        make_check(
            "index_valuation", "pe_cross_source_max_rel_diff",
            pe_cross["max_rel_diff"], PE_CROSS_SOURCE_MAX_REL_DIFF,
            rule="max", severity="warn",
            detail={"samples": pe_cross["samples"], "window_days": PE_CROSS_SOURCE_WINDOW_DAYS},
        )
    )

    # 10) backlog
    backlog = load_backlog_total(conn)
    checks.append(
        make_check(
            "backlog", "backlog_total", backlog, BACKLOG_MAX, rule="max",
            severity="error", detail={"limit": BACKLOG_MAX},
        )
    )

    summary = {
        "ok": sum(1 for check in checks if check.status == "ok"),
        "warn": sum(1 for check in checks if check.status == "warn"),
        "error": sum(1 for check in checks if check.status == "error"),
        "total": len(checks),
    }
    return {
        "stat_date": expected.isoformat(),
        "reference_date": reference.isoformat(),
        "generated_at": datetime.now(CN).isoformat(),
        "datasets": list(AUDIT_DATASETS),
        # bp_data_freshness 读侧真值（8 类 as_of/status/source）：与体检重算结果互相印证
        "freshness": load_freshness(conn),
        "checks": [check.__dict__ for check in checks],
        "summary": summary,
        "exit_code": 1 if summary["error"] else 0,
    }


# ---------------------------------------------------------------------------
# 落库
# ---------------------------------------------------------------------------
AUDIT_UPSERT_SQL = (
    "INSERT INTO bp_data_audit_daily"
    " (dataset, stat_date, metric, value, threshold, status, detail)"
    " VALUES (%s, %s, %s, %s, %s, %s, %s::jsonb)"
    " ON CONFLICT (dataset, stat_date, metric) DO UPDATE SET"
    " value = EXCLUDED.value, threshold = EXCLUDED.threshold,"
    " status = EXCLUDED.status, detail = EXCLUDED.detail, created_at = now()"
)


def persist(conn: Any, report: Mapping[str, Any], *, write_issues: bool = True) -> dict[str, Any]:
    """把检查写 bp_data_audit_daily + 非 ok 检查写 bp_etl_quality_issue（调用方 commit）。"""
    from bp_etl.health import record_issues  # noqa: PLC0415

    stat_date = date.fromisoformat(str(report["stat_date"]))
    checks = report.get("checks") or []
    rows = [
        (
            check["dataset"], stat_date, check["metric"], check["value"],
            check["threshold"], check["status"],
            json.dumps(check.get("detail") or {}, ensure_ascii=False, default=str),
        )
        for check in checks
    ]
    written = 0
    with conn.cursor() as cur:
        cur.executemany(AUDIT_UPSERT_SQL, rows)
        written = len(rows)
    issues: list[QualityIssue] = []
    if write_issues:
        for check in checks:
            if check.get("status") == "ok":
                continue
            issues.append(
                QualityIssue(
                    dataset=str(check["dataset"]),
                    kind=f"audit:{check['metric']}",
                    severity="error" if check.get("status") == "error" else "warn",
                    trade_date=stat_date,
                    detail={
                        "metric": check["metric"],
                        "value": check.get("value"),
                        "threshold": check.get("threshold"),
                        **(check.get("detail") or {}),
                    },
                )
            )
        if issues:
            record_issues(conn, issues)
    return {"rows_written": written, "issues_written": len(issues)}


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------
def _connect():
    from bp_ingest.config import load_config  # noqa: PLC0415
    from bp_ingest.db import connect  # noqa: PLC0415

    return connect(load_config().db)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="daily_data_audit.py",
        description="每日 09:30 全站数据体检（8 类数据覆盖率/时效/准确性）",
    )
    parser.add_argument("--date", dest="date", default=None,
                        help="参考日 YYYY-MM-DD（默认今天；应到交易日取 <= 该日的最近交易日）")
    parser.add_argument("--dry-run", action="store_true", help="只输出报告，不写库")
    parser.add_argument("--output", default=None, help="额外把 JSON 报告写入该文件")
    parser.add_argument("--skip-accuracy", action="store_true", help="跳过准确性检查")
    parser.add_argument("--log-level", default="INFO")
    return parser


def main(argv: Optional[Sequence[str]] = None) -> int:
    args = build_parser().parse_args(argv)
    logging.basicConfig(
        level=getattr(logging, str(args.log_level).upper(), logging.INFO),
        format="%(asctime)s | %(levelname)-7s | %(name)s | %(message)s",
    )
    reference = date.fromisoformat(args.date) if args.date else date.today()
    from bp_ingest.config import load_config  # noqa: PLC0415
    from bp_ingest.db import connect  # noqa: PLC0415

    # bp_ingest.db.connect 是 @contextmanager（yield 连接并按块提交/回滚），
    # 不能直接当连接对象用；历史上误用导致 '_GeneratorContextManager' has no attribute cursor。
    with connect(load_config().db) as conn:
        conn.autocommit = False
        report = audit(conn, reference=reference)
        if args.skip_accuracy:
            report["checks"] = [
                check for check in report["checks"]
                if not check["metric"].startswith(
                    ("ohlc_", "return_jump_", "cross_source_")
                )
            ]
            summary = {
                "ok": sum(1 for c in report["checks"] if c["status"] == "ok"),
                "warn": sum(1 for c in report["checks"] if c["status"] == "warn"),
                "error": sum(1 for c in report["checks"] if c["status"] == "error"),
                "total": len(report["checks"]),
            }
            report["summary"] = summary
            report["exit_code"] = 1 if summary["error"] else 0
        if args.dry_run:
            report["persisted"] = None
        else:
            report["persisted"] = persist(conn, report)
            conn.commit()
    text = json.dumps(report, ensure_ascii=False, default=str, indent=1)
    print(text)
    if args.output:
        with open(args.output, "w", encoding="utf-8") as handle:
            handle.write(text + "\n")
    return int(report.get("exit_code") or 0)


if __name__ == "__main__":
    sys.exit(main())