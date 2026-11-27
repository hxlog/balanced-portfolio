"""指数估值域数据访问层（``bp_index_master`` / 估值三表）。

契约见 ``docs/index-valuation/15-p0-contracts.md`` §2：

- 全部函数签名为 ``(conn, ...)``，使用 ``conn.cursor()``；
- **不 commit**，事务边界由调用方控制；
- 写操作全部 ``ON CONFLICT DO UPDATE``，保证重复执行幂等；
- 数值出参统一 ``float | None``（``Decimal -> float``）；
- ``get_index_list`` 只发一条 SQL（CTE + LATERAL），杜绝 N+1。
"""

from __future__ import annotations

import math
from datetime import date, datetime
from decimal import Decimal
from typing import Any, Optional

import numpy as np
import pandas as pd
import psycopg
from psycopg.types.json import Json

from .repositories import _json_safe

CALC_SRC_PINGAN = "pingan_index"

INDEX_MARKETS = frozenset({"CSI", "SH", "SZ", "CNI", "HK", "US", "BJ", "GLOBAL"})
SERIES_METRICS = frozenset(
    {
        "pe_ttm",
        "pe_static",
        "pb",
        "dividend_yield_ttm",
        "dividend_yield_lyr",
        "erp",
    }
)
PERCENTILE_WINDOWS = frozenset({"1y", "3y", "5y", "10y", "all"})
LEVELS = frozenset({"低估", "中性", "高估"})


# ---------------------------------------------------------------------------
# 类型清洗（psycopg 拒绝 NaN/Infinity；Decimal 统一转 float）
# ---------------------------------------------------------------------------


def _to_float(value: Any) -> Optional[float]:
    if value is None or isinstance(value, bool):
        return None
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if math.isfinite(number) else None


def _to_int(value: Any) -> Optional[int]:
    if value is None or isinstance(value, bool):
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _to_text(value: Any) -> Optional[str]:
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def _to_date(value: Any) -> Optional[date]:
    if value is None:
        return None
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    if isinstance(value, str):
        text = value.strip()
        for fmt in ("%Y-%m-%d", "%Y%m%d"):
            try:
                return datetime.strptime(text, fmt).date()
            except ValueError:
                continue
    return None


def _json_ready(value: Any) -> Any:
    """把 date/Decimal 等非 JSON 原生类型转为可序列化值，再交给 ``_json_safe``。"""
    if isinstance(value, dict):
        return {str(key): _json_ready(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_json_ready(item) for item in value]
    if isinstance(value, (datetime, date)):
        return value.isoformat()
    if isinstance(value, Decimal):
        return float(value)
    return value


def _json_value(raw: Any) -> Optional[Json]:
    if raw is None:
        return None
    return Json(_json_safe(_json_ready(raw)))


def _bounded(value: Any, low: float, high: float) -> Optional[float]:
    number = _to_float(value)
    if number is None or not low <= number <= high:
        return None
    return number


def _positive(value: Any) -> Optional[float]:
    number = _to_float(value)
    return number if number is not None and number > 0 else None


def _level(value: Any) -> Optional[str]:
    text = _to_text(value)
    return text if text in LEVELS else None


def _affected(cur: psycopg.Cursor, attempted: int) -> int:
    if attempted == 0:
        return 0
    rowcount = cur.rowcount
    if rowcount is None or rowcount < 0:
        return attempted
    return int(rowcount)


def _shift_years(day: date, years: int) -> date:
    try:
        return day.replace(year=day.year + years)
    except ValueError:  # 2/29 -> 非闰年
        return day.replace(year=day.year + years, month=2, day=28)


# ---------------------------------------------------------------------------
# 写入
# ---------------------------------------------------------------------------


def upsert_index_master(conn: psycopg.Connection, rows: list[dict]) -> int:
    """upsert 指数主数据，冲突键 ``index_code``。返回受影响行数。"""
    records: list[tuple] = []
    for row in rows:
        index_code = _to_text(row.get("index_code"))
        market = _to_text(row.get("market"))
        name = _to_text(row.get("name"))
        if not index_code or market not in INDEX_MARKETS or not name:
            continue
        records.append(
            (
                index_code,
                market,
                _to_text(row.get("wind_code")),
                name,
                _to_text(row.get("short_name")),
                _to_text(row.get("index_type")),
                _to_text(row.get("publisher")),
                _to_date(row.get("base_date")),
                _to_float(row.get("base_point")),
                _to_text(row.get("income_method")),
                _to_text(row.get("weight_method")),
                _to_text(row.get("intro")),
                True if row.get("is_active") is None else bool(row["is_active"]),
                True if row.get("is_tracked") is None else bool(row["is_tracked"]),
            )
        )
    if not records:
        return 0

    sql = """
        INSERT INTO bp_index_master (
            index_code, market, wind_code, name, short_name, index_type,
            publisher, base_date, base_point, income_method, weight_method,
            intro, is_active, is_tracked
        ) VALUES (
            %s, %s, %s, %s, %s, %s,
            %s, %s, %s, %s, %s,
            %s, %s, %s
        )
        ON CONFLICT (index_code) DO UPDATE SET
            market = EXCLUDED.market,
            wind_code = EXCLUDED.wind_code,
            name = EXCLUDED.name,
            short_name = EXCLUDED.short_name,
            index_type = EXCLUDED.index_type,
            publisher = EXCLUDED.publisher,
            base_date = EXCLUDED.base_date,
            base_point = EXCLUDED.base_point,
            income_method = EXCLUDED.income_method,
            weight_method = EXCLUDED.weight_method,
            intro = EXCLUDED.intro,
            is_active = EXCLUDED.is_active,
            is_tracked = EXCLUDED.is_tracked,
            updated_at = now()
    """
    with conn.cursor() as cur:
        cur.executemany(sql, records)
        return _affected(cur, len(records))


def upsert_valuation_daily(conn: psycopg.Connection, rows: list[dict]) -> int:
    """upsert 日频估值宽表，冲突键 ``(index_code, trade_date, calc_src)``。

    ``captured_at`` 只在首次插入时写，重复执行不重写（PiT 审计）。
    """
    records: list[tuple] = []
    for row in rows:
        index_code = _to_text(row.get("index_code"))
        trade_date = _to_date(row.get("trade_date"))
        calc_src = _to_text(row.get("calc_src"))
        if not index_code or trade_date is None or not calc_src:
            continue
        records.append(
            (
                index_code,
                trade_date,
                calc_src,
                _positive(row.get("pe_ttm")),
                _positive(row.get("pe_static")),
                _positive(row.get("pb")),
                _bounded(row.get("dividend_yield_ttm"), -100.0, 100.0),
                _bounded(row.get("dividend_yield_lyr"), -100.0, 100.0),
                _to_float(row.get("roe_ttm")),
                _to_float(row.get("roa_ttm")),
                _to_float(row.get("bond10y")),
                _to_float(row.get("erp")),
                _to_text(row.get("pe_basis")),
                _to_text(row.get("pb_basis")),
                _to_text(row.get("div_basis")),
                _level(row.get("level_pe")),
                _level(row.get("level_pb")),
                _level(row.get("level_dividend")),
                bool(row.get("is_primary", False)),
                _json_value(row.get("raw")),
            )
        )
    if not records:
        return 0

    sql = """
        INSERT INTO bp_index_valuation_daily (
            index_code, trade_date, calc_src, pe_ttm, pe_static, pb,
            dividend_yield_ttm, dividend_yield_lyr, roe_ttm, roa_ttm,
            bond10y, erp, pe_basis, pb_basis, div_basis,
            level_pe, level_pb, level_dividend, is_primary, raw
        ) VALUES (
            %s, %s, %s, %s, %s, %s,
            %s, %s, %s, %s,
            %s, %s, %s, %s, %s,
            %s, %s, %s, %s, %s
        )
        ON CONFLICT (index_code, trade_date, calc_src) DO UPDATE SET
            pe_ttm = EXCLUDED.pe_ttm,
            pe_static = EXCLUDED.pe_static,
            pb = EXCLUDED.pb,
            dividend_yield_ttm = EXCLUDED.dividend_yield_ttm,
            dividend_yield_lyr = EXCLUDED.dividend_yield_lyr,
            roe_ttm = EXCLUDED.roe_ttm,
            roa_ttm = EXCLUDED.roa_ttm,
            bond10y = EXCLUDED.bond10y,
            erp = EXCLUDED.erp,
            pe_basis = EXCLUDED.pe_basis,
            pb_basis = EXCLUDED.pb_basis,
            div_basis = EXCLUDED.div_basis,
            level_pe = EXCLUDED.level_pe,
            level_pb = EXCLUDED.level_pb,
            level_dividend = EXCLUDED.level_dividend,
            is_primary = EXCLUDED.is_primary,
            raw = EXCLUDED.raw
    """
    with conn.cursor() as cur:
        cur.executemany(sql, records)
        return _affected(cur, len(records))


def upsert_valuation_series(conn: psycopg.Connection, rows: list[dict]) -> int:
    """upsert 估值历史长表，冲突键 ``(index_code, trade_date, metric, calc_src)``。"""
    records: list[tuple] = []
    for row in rows:
        index_code = _to_text(row.get("index_code"))
        trade_date = _to_date(row.get("trade_date"))
        metric = _to_text(row.get("metric"))
        calc_src = _to_text(row.get("calc_src"))
        value = _to_float(row.get("value"))
        if (
            not index_code
            or trade_date is None
            or metric not in SERIES_METRICS
            or not calc_src
            or value is None
        ):
            continue
        records.append(
            (
                index_code,
                trade_date,
                metric,
                calc_src,
                value,
                bool(row.get("is_weekly", False)),
            )
        )
    if not records:
        return 0

    sql = """
        INSERT INTO bp_index_valuation_series (
            index_code, trade_date, metric, calc_src, value, is_weekly
        ) VALUES (%s, %s, %s, %s, %s, %s)
        ON CONFLICT (index_code, trade_date, metric, calc_src) DO UPDATE SET
            value = EXCLUDED.value,
            is_weekly = EXCLUDED.is_weekly
    """
    with conn.cursor() as cur:
        cur.executemany(sql, records)
        return _affected(cur, len(records))


def upsert_percentiles(conn: psycopg.Connection, rows: list[dict]) -> int:
    """upsert 分位预计算，冲突键 ``(index_code, as_of_date, metric, window_key, calc_src)``。"""
    records: list[tuple] = []
    for row in rows:
        index_code = _to_text(row.get("index_code"))
        as_of_date = _to_date(row.get("as_of_date"))
        metric = _to_text(row.get("metric"))
        window_key = _to_text(row.get("window_key"))
        calc_src = _to_text(row.get("calc_src"))
        sample_size = _to_int(row.get("sample_size"))
        if (
            not index_code
            or as_of_date is None
            or metric not in SERIES_METRICS
            or window_key not in PERCENTILE_WINDOWS
            or not calc_src
            or sample_size is None
            or sample_size < 0
        ):
            continue
        records.append(
            (
                index_code,
                as_of_date,
                metric,
                window_key,
                calc_src,
                _to_float(row.get("pct")),
                _to_float(row.get("mean")),
                _to_float(row.get("sd")),
                _to_float(row.get("p20")),
                _to_float(row.get("p50")),
                _to_float(row.get("p80")),
                _to_float(row.get("min_value")),
                _to_float(row.get("max_value")),
                sample_size,
            )
        )
    if not records:
        return 0

    sql = """
        INSERT INTO bp_index_percentile (
            index_code, as_of_date, metric, window_key, calc_src,
            pct, mean, sd, p20, p50, p80, min_value, max_value, sample_size
        ) VALUES (
            %s, %s, %s, %s, %s,
            %s, %s, %s, %s, %s, %s, %s, %s, %s
        )
        ON CONFLICT (index_code, as_of_date, metric, window_key, calc_src) DO UPDATE SET
            pct = EXCLUDED.pct,
            mean = EXCLUDED.mean,
            sd = EXCLUDED.sd,
            p20 = EXCLUDED.p20,
            p50 = EXCLUDED.p50,
            p80 = EXCLUDED.p80,
            min_value = EXCLUDED.min_value,
            max_value = EXCLUDED.max_value,
            sample_size = EXCLUDED.sample_size,
            computed_at = now()
    """
    with conn.cursor() as cur:
        cur.executemany(sql, records)
        return _affected(cur, len(records))


# ---------------------------------------------------------------------------
# 读取
# ---------------------------------------------------------------------------


def fetch_series(
    conn: psycopg.Connection,
    index_code: str,
    metric: str,
    calc_src: str,
    start: Optional[date],
    end: Optional[date],
) -> list[tuple[date, float]]:
    """读取某指数/指标/来源的序列，按交易日升序；``start``/``end`` 可空。"""
    sql = (
        "SELECT trade_date, value FROM bp_index_valuation_series "
        "WHERE index_code = %s AND metric = %s AND calc_src = %s"
    )
    params: list[Any] = [index_code, metric, calc_src]
    if start is not None:
        sql += " AND trade_date >= %s"
        params.append(start)
    if end is not None:
        sql += " AND trade_date <= %s"
        params.append(end)
    sql += " ORDER BY trade_date"

    with conn.cursor() as cur:
        cur.execute(sql, params)
        result: list[tuple[date, float]] = []
        for trade_date, value in cur.fetchall():
            number = _to_float(value)
            if trade_date is not None and number is not None:
                result.append((trade_date, number))
        return result


def get_market_overview(
    conn: psycopg.Connection, as_of: Optional[date] = None
) -> list[dict]:
    """全市场/板块估值概览；``as_of`` 为空时取最近一天。"""
    sql = """
        SELECT
            d.board,
            d.trade_date,
            d.pe_median,
            d.pe_equal,
            d.pb_median,
            d.pb_equal,
            d.pct_pe,
            d.pct_pb,
            d.sample_size,
            d.calc_src,
            (
                SELECT count(*)
                FROM bp_market_valuation_daily h
                WHERE h.board = d.board AND h.trade_date <= d.trade_date
            ) AS history_days
        FROM bp_market_valuation_daily d
        WHERE d.trade_date = COALESCE(
            (
                SELECT max(m.trade_date)
                FROM bp_market_valuation_daily m
                WHERE m.trade_date = %s::date
            ),
            (SELECT max(m.trade_date) FROM bp_market_valuation_daily m)
        )
        ORDER BY d.board
    """
    numeric_fields = {
        "pe_median",
        "pe_equal",
        "pb_median",
        "pb_equal",
        "pct_pe",
        "pct_pb",
    }
    with conn.cursor() as cur:
        cur.execute(sql, (as_of,))
        columns = [desc.name for desc in cur.description]
        rows: list[dict] = []
        for record in cur.fetchall():
            item = dict(zip(columns, record))
            for key in numeric_fields:
                item[key] = _to_float(item.get(key))
            item["sample_size"] = int(item.get("sample_size") or 0)
            item["history_days"] = int(item.get("history_days") or 0)
            rows.append(item)
        return rows


def get_index_risk_stats(conn: psycopg.Connection, index_code: str) -> dict:
    """指数区间收益风险统计（基于原始行情收盘）。

    返回 1/3/5 年与全区间：区间收益、年化收益、年化波动、最大回撤、夏普（rf=0）。
    数据来自 bp_index_quote_daily(bfq)，无行情的指数返回空 dict。
    """
    sql = """
        SELECT trade_date, close
        FROM bp_index_quote_daily
        WHERE symbol = %s AND adjust = 'bfq' AND close IS NOT NULL
        ORDER BY trade_date
    """
    with conn.cursor() as cur:
        cur.execute(sql, (index_code,))
        rows = cur.fetchall()
    if len(rows) < 30:
        return {}

    import math

    def window_stats(points: list[tuple], years: float | None) -> dict | None:
        if len(points) < 30:
            return None
        first = float(points[0][1])
        last = float(points[-1][1])
        if first <= 0:
            return None
        total = (last / first - 1) * 100
        span_days = max((points[-1][0] - points[0][0]).days, 1)
        ann_factor = 365.0 / span_days
        annual = ((last / first) ** ann_factor - 1) * 100 if last > 0 else None
        returns: list[float] = []
        peak = first
        max_dd = 0.0
        for _, close in points[1:]:
            value = float(close)
            if value <= 0:
                continue
            returns.append(value / peak - 1)
            peak = max(peak, value)
        # 用相邻收盘算日收益（上面 returns 是相对峰值，仅用于回撤）
        daily: list[float] = []
        prev = first
        for _, close in points[1:]:
            value = float(close)
            if prev > 0:
                daily.append(value / prev - 1)
            prev = value
        peak = first
        for value in [float(item[1]) for item in points]:
            peak = max(peak, value)
            if peak > 0:
                max_dd = min(max_dd, value / peak - 1)
        vol = None
        if len(daily) > 2:
            mean = sum(daily) / len(daily)
            variance = sum((item - mean) ** 2 for item in daily) / (len(daily) - 1)
            vol = math.sqrt(variance) * math.sqrt(252) * 100
        sharpe = None
        if ann_factor and vol and vol > 0 and years is not None:
            # 年化收益减无风险收益（这里用 0，页面上注明未扣减）
            sharpe = annual / vol if annual is not None else None
        return {
            "total_return_pct": round(total, 4),
            "annualized_return_pct": None if annual is None else round(annual, 4),
            "volatility_pct": None if vol is None else round(vol, 4),
            "max_drawdown_pct": round(max_dd * 100, 4),
            "sharpe": None if sharpe is None else round(sharpe, 4),
            "sample_size": len(points),
        }

    def slice_years(points: list[tuple], years: float) -> list[tuple]:
        if not points:
            return []
        end = points[-1][0]
        target = end.replace(year=max(end.year - int(years), 1900))
        return [item for item in points if item[0] >= target]

    windows = {
        "1y": slice_years(rows, 1),
        "3y": slice_years(rows, 3),
        "5y": slice_years(rows, 5),
        "all": rows,
    }
    out: dict = {}
    for key, points in windows.items():
        stats = window_stats(points, None if key == "all" else int(key[0]))
        if stats is not None:
            out[key] = stats
    return out

def get_broad_proxies(
    conn: psycopg.Connection,
    codes: list[str],
    window: str = "5y",
) -> list[dict]:
    """代表性宽基指数的「最新估值 + 所选窗口分位」。

    用于首页全市场估值卡片：用上证50/沪深300/中证A500/中证1000/中证全指等
    有完整估值序列的宽基做代理，避免用只有单日样本的截面数据算假分位。
    """
    if not codes:
        return []
    safe_window = window if window in PERCENTILE_WINDOWS else "5y"
    sql = """
        SELECT
            m.index_code,
            m.name,
            m.industry,
            v.trade_date,
            v.pe_ttm,
            v.pb,
            v.dividend_yield_ttm,
            v.erp,
            (array_agg(p.pct ORDER BY p.as_of_date DESC)
                FILTER (WHERE p.metric = 'pe_ttm'))[1] AS pe_percentile,
            (array_agg(p.pct ORDER BY p.as_of_date DESC)
                FILTER (WHERE p.metric = 'pb'))[1] AS pb_percentile,
            max(p.as_of_date) AS pct_as_of
        FROM bp_index_master m
        LEFT JOIN LATERAL (
            SELECT d.index_code, d.trade_date, d.pe_ttm, d.pb,
                   d.dividend_yield_ttm, d.erp, d.calc_src
            FROM bp_index_valuation_daily d
            WHERE d.index_code = m.index_code AND d.is_primary
            ORDER BY d.trade_date DESC
            LIMIT 1
        ) v ON TRUE
        LEFT JOIN LATERAL (
            SELECT p.pct, p.metric, p.as_of_date
            FROM bp_index_percentile p
            WHERE p.index_code = m.index_code
              AND p.window_key = %(window)s
              AND p.calc_src = v.calc_src
        ) p ON TRUE
        WHERE m.index_code = ANY(%(codes)s)
        GROUP BY m.index_code, m.name, m.industry, v.trade_date,
                 v.pe_ttm, v.pb, v.dividend_yield_ttm, v.erp
        ORDER BY m.index_code
    """
    with conn.cursor() as cur:
        cur.execute(sql, {"codes": codes, "window": safe_window})
        columns = [desc.name for desc in cur.description]
        records = cur.fetchall()
    numeric = {
        "pe_ttm", "pb", "dividend_yield_ttm", "erp",
        "pe_percentile", "pb_percentile",
    }
    out: list[dict] = []
    for record in records:
        item = dict(zip(columns, record))
        for key in numeric:
            item[key] = _to_float(item.get(key))
        item["window"] = safe_window
        out.append(item)
    return out

def get_index_list(
    conn: psycopg.Connection,
    *,
    query: Optional[str],
    index_type: Optional[str],
    industry: Optional[str] = None,
    window: str = "5y",
    metric: str = "pe_ttm",
    only_with_etf: bool,
    only_with_valuation: bool,
    limit: int,
    offset: int,
) -> tuple[list[dict], int]:
    """指数列表（单条 SQL）。

    一条 CTE + 若干 LATERAL 完成「主数据 + 最新主口径估值 + 多指标分位（按窗口）
    + 全历史高低点」，并用锚点行保证空页也能拿到 total，绝不产生 N+1。

    window/metric 只影响返回的分位口径；PE/PB/股息率/ERP 四个分位会一起返回，
    前端切换指标与窗口无需新接口。
    """
    limit = max(0, int(limit))
    offset = max(0, int(offset))
    query_text = _to_text(query)
    query_like = f"%{query_text}%" if query_text else None

    sql = """
        WITH matched AS (
            SELECT
                m.index_code,
                m.name,
                m.short_name,
                m.index_type,
                m.industry,
                m.market,
                fs.fund_count,
                fs.aum_sum AS fund_aum,
                h.status AS quote_status,
                h.lag_trading_days,
                m.publisher,
                v.trade_date,
                v.calc_src,
                v.pe_ttm,
                v.pb,
                v.dividend_yield_ttm,
                v.erp,
                v.roe_ttm,
                v.level_pe,
                v.level_pb,
                v.level_dividend,
                v.captured_at,
                (v.index_code IS NOT NULL) AS has_valuation,
                COALESCE(
                    jsonb_typeof(v.raw -> 'etf_fund') = 'array'
                    AND jsonb_array_length(v.raw -> 'etf_fund') > 0,
                    FALSE
                ) AS has_etf,
                qp.close_last AS close_price,
                CASE
                    WHEN qp.close_last > 0 AND qp.close_prev > 0
                    THEN ((qp.close_last / qp.close_prev) - 1) * 100
                END AS change_pct,
                -- 只有样本足够（>=200 个交易日）才宣称 52 周高低，避免用 24 天数据冒充
                CASE WHEN qp.obs_52w >= 200 THEN qp.high_52w END AS high_52w,
                CASE WHEN qp.obs_52w >= 200 THEN qp.low_52w END AS low_52w,
                COALESCE(
                    CASE
                        WHEN qp.close_last > 0 AND qp.close_7d_ago > 0
                        THEN ((qp.close_last / qp.close_7d_ago) - 1) * 100
                    END,
                    CASE
                        WHEN (v.raw ->> 'rise_week') ~ '^-?[0-9.]+$'
                        THEN (v.raw ->> 'rise_week')::numeric
                    END
                ) AS change_7d_pct,
                CASE
                    WHEN qp.obs_52w >= 200 AND qp.high_52w > 0 AND qp.close_last IS NOT NULL
                    THEN ((qp.close_last / qp.high_52w) - 1) * 100
                END AS dist_from_high_pct,
                CASE
                    WHEN qp.obs_52w >= 200 AND qp.high_52w > qp.low_52w AND qp.close_last IS NOT NULL
                    THEN ((qp.close_last - qp.low_52w) / (qp.high_52w - qp.low_52w)) * 100
                END AS position_52w_pct,
                pc.pe_pct AS pe_percentile,
                pc.pb_pct AS pb_percentile,
                pc.div_pct AS dividend_percentile,
                pc.erp_pct AS erp_percentile,
                pc.as_of_date AS pct_as_of,
                CASE %(metric)s
                    WHEN 'pe_ttm' THEN pc.pe_pct
                    WHEN 'pb' THEN pc.pb_pct
                    WHEN 'dividend_yield_ttm' THEN pc.div_pct
                    WHEN 'erp' THEN pc.erp_pct
                END AS metric_percentile,
                qh.high_all,
                CASE
                    WHEN qh.high_all > 0 AND qp.close_last IS NOT NULL
                    THEN ((qp.close_last / qh.high_all) - 1) * 100
                END AS dist_from_all_high_pct,
                COALESCE(
                    CASE
                        WHEN qh.close_52w_ago > 0 AND qp.close_last > 0
                        THEN ((qp.close_last / qh.close_52w_ago) - 1) * 100
                    END,
                    CASE
                        WHEN (v.raw ->> 'rise_year') ~ '^-?[0-9.]+$'
                        THEN (v.raw ->> 'rise_year')::numeric
                    END
                ) AS change_52w_pct
            FROM bp_index_master m
            LEFT JOIN LATERAL (
                SELECT
                    d.index_code, d.trade_date, d.calc_src, d.pe_ttm, d.pb,
                    d.dividend_yield_ttm, d.erp, d.roe_ttm,
                    d.level_pe, d.level_pb, d.level_dividend, d.captured_at, d.raw
                FROM bp_index_valuation_daily d
                WHERE d.index_code = m.index_code AND d.is_primary
                ORDER BY d.trade_date DESC
                LIMIT 1
            ) v ON TRUE
            LEFT JOIN LATERAL (
                SELECT
                    (array_agg(p.pct ORDER BY p.as_of_date DESC)
                        FILTER (WHERE p.metric = 'pe_ttm'))[1] AS pe_pct,
                    (array_agg(p.pct ORDER BY p.as_of_date DESC)
                        FILTER (WHERE p.metric = 'pb'))[1] AS pb_pct,
                    (array_agg(p.pct ORDER BY p.as_of_date DESC)
                        FILTER (WHERE p.metric = 'dividend_yield_ttm'))[1] AS div_pct,
                    (array_agg(p.pct ORDER BY p.as_of_date DESC)
                        FILTER (WHERE p.metric = 'erp'))[1] AS erp_pct,
                    max(p.as_of_date) AS as_of_date
                FROM bp_index_percentile p
                WHERE p.index_code = m.index_code
                  AND p.window_key = %(window)s
                  AND p.calc_src = v.calc_src
            ) pc ON TRUE
            -- 一次扫过去 400 天：最近两根收盘 + 7 日前收盘 + 52 周高低（chunk 裁剪靠时间下界）。
            LEFT JOIN LATERAL (
                SELECT
                    (array_agg(t.close ORDER BY t.trade_date DESC))[1] AS close_last,
                    (array_agg(t.close ORDER BY t.trade_date DESC))[2] AS close_prev,
                    (array_agg(t.close ORDER BY t.trade_date DESC))[8] AS close_7d_ago,
                    max(t.close) AS high_52w,
                    min(t.close) AS low_52w,
                    count(*) AS obs_52w,
                    max(t.trade_date) AS trade_date
                FROM (
                    -- 指数点位是原币口径，直接读原始行情表即可；清洗表含 CNY 折算，
                    -- 且只覆盖进入资产池的标的（不会包含 521 只估值指数的全部）。
                    SELECT q.close, q.trade_date
                    FROM bp_index_quote_daily q
                    WHERE q.symbol = m.index_code
                      AND q.adjust = 'bfq'
                      AND q.trade_date >= current_date - 400
                ) t
            ) qp ON TRUE
            -- 跟踪基金规模：读预计算表（65 号迁移），避免 521 次 LATERAL 聚合
            LEFT JOIN bp_index_fund_scale fs ON fs.index_code = m.index_code
            LEFT JOIN bp_index_quote_health h ON h.symbol = m.index_code
            -- 区间最高 / 52 周前收盘：读预计算表（64 号迁移），避免每次全历史扫行情表
            LEFT JOIN bp_index_quote_extremes qh ON qh.symbol = m.index_code
            WHERE (%(query)s::text IS NULL
                   OR m.index_code ILIKE %(query_like)s
                   OR m.name ILIKE %(query_like)s
                   OR COALESCE(m.short_name, '') ILIKE %(query_like)s)
              AND (%(index_type)s::text IS NULL
                   OR m.index_type = %(index_type)s::text)
              AND (%(industry)s::text IS NULL
                   OR m.industry = %(industry)s::text)
              AND (NOT %(only_with_valuation)s OR v.index_code IS NOT NULL)
              AND (NOT %(only_with_etf)s
                   OR (jsonb_typeof(v.raw -> 'etf_fund') = 'array'
                       AND jsonb_array_length(v.raw -> 'etf_fund') > 0))
        )
        SELECT (SELECT count(*) FROM matched) AS total_count, page.*
        FROM (SELECT 1) AS anchor
        LEFT JOIN LATERAL (
            SELECT * FROM matched
            ORDER BY index_code
            LIMIT %(limit)s OFFSET %(offset)s
        ) AS page ON TRUE
    """
    params = {
        "query": query_text,
        "query_like": query_like,
        "index_type": _to_text(index_type),
        "industry": _to_text(industry),
        "window": window if window in PERCENTILE_WINDOWS else "5y",
        "metric": metric if metric in SERIES_METRICS else "pe_ttm",
        "only_with_valuation": bool(only_with_valuation),
        "only_with_etf": bool(only_with_etf),
        "limit": limit,
        "offset": offset,
    }
    numeric_fields = {
        "pe_ttm",
        "pb",
        "dividend_yield_ttm",
        "erp",
        "pe_percentile",
        "pb_percentile",
        "dividend_percentile",
        "erp_percentile",
        "metric_percentile",
        "close_price",
        "change_pct",
        "high_all",
        "dist_from_all_high_pct",
        "change_52w_pct",
        "roe_ttm",
        "fund_aum",
        "fund_count",
        "quote_lag_days",
    }
    with conn.cursor() as cur:
        cur.execute(sql, params)
        columns = [desc.name for desc in cur.description]
        records = cur.fetchall()
    if not records:
        return [], 0

    total = int(records[0][0] or 0)
    rows: list[dict] = []
    for record in records:
        item = dict(zip(columns, record))
        if item.get("index_code") is None:
            continue
        item.pop("total_count", None)
        for key in numeric_fields:
            item[key] = _to_float(item.get(key))
        item["has_valuation"] = bool(item.get("has_valuation"))
        item["has_etf"] = bool(item.get("has_etf"))
        rows.append(item)
    return rows, total


def get_index_detail(conn: psycopg.Connection, index_code: str) -> Optional[dict]:
    """指数详情 = 主数据 + 最新主口径估值 + 最新分位 + raw 中的成分/跟踪基金。"""
    sql = """
        SELECT
            m.index_code, m.market, m.wind_code, m.name, m.short_name,
            m.index_type, m.publisher, m.base_date, m.base_point,
            m.income_method, m.weight_method, m.intro, m.is_active, m.is_tracked, m.industry,
            d.trade_date, d.calc_src, d.pe_ttm, d.pe_static, d.pb,
            d.dividend_yield_ttm, d.dividend_yield_lyr, d.roe_ttm, d.roa_ttm,
            d.bond10y, d.erp, d.pe_basis, d.pb_basis, d.div_basis,
            d.level_pe, d.level_pb, d.level_dividend, d.is_primary,
            d.captured_at, d.raw,
            qq.close_last AS close_price,
            CASE
                WHEN qq.close_last > 0 AND qq.close_prev > 0
                THEN ((qq.close_last / qq.close_prev) - 1) * 100
            END AS change_pct
        FROM bp_index_master m
        LEFT JOIN LATERAL (
            SELECT *
            FROM bp_index_valuation_daily dd
            WHERE dd.index_code = m.index_code AND dd.is_primary
            ORDER BY dd.trade_date DESC
            LIMIT 1
        ) d ON TRUE
        LEFT JOIN LATERAL (
            SELECT
                (array_agg(t.close ORDER BY t.trade_date DESC))[1] AS close_last,
                (array_agg(t.close ORDER BY t.trade_date DESC))[2] AS close_prev
            FROM (
                SELECT q.close, q.trade_date
                FROM bp_index_quote_daily q
                WHERE q.symbol = m.index_code
                  AND q.adjust = 'bfq'
                  AND q.trade_date >= current_date - 400
            ) t
        ) qq ON TRUE
        WHERE m.index_code = %s
    """
    with conn.cursor() as cur:
        cur.execute(sql, (index_code,))
        record = cur.fetchone()
        if record is None:
            return None
        columns = [desc.name for desc in cur.description]
        detail = dict(zip(columns, record))

    numeric_fields = {
        "base_point",
        "pe_ttm",
        "pe_static",
        "pb",
        "dividend_yield_ttm",
        "dividend_yield_lyr",
        "roe_ttm",
        "roa_ttm",
        "bond10y",
        "erp",
        "close_price",
        "change_pct",
    }
    for key in numeric_fields:
        detail[key] = _to_float(detail.get(key))
    if detail.get("is_primary") is not None:
        detail["is_primary"] = bool(detail["is_primary"])

    percentile_sql = """
        SELECT
            metric, window_key, as_of_date, calc_src,
            pct, mean, sd, p20, p50, p80, min_value, max_value, sample_size
        FROM bp_index_percentile
        WHERE index_code = %s
          AND as_of_date = (
              SELECT max(as_of_date)
              FROM bp_index_percentile
              WHERE index_code = %s
          )
          AND (%s::text IS NULL OR calc_src = %s::text)
        ORDER BY metric, window_key
    """
    calc_src = detail.get("calc_src")
    with conn.cursor() as cur:
        cur.execute(percentile_sql, (index_code, index_code, calc_src, calc_src))
        columns = [desc.name for desc in cur.description]
        percentile_rows = [dict(zip(columns, row)) for row in cur.fetchall()]

    # 与 API 消费方（bp_api/valuation.py::_history_stats）对齐：列表形式，
    # 每行自带 metric/window_key，调用方按 (metric, window) 精确取用。
    percentiles: list[dict] = []
    for row in percentile_rows:
        for key in (
            "pct",
            "mean",
            "sd",
            "p20",
            "p50",
            "p80",
            "min_value",
            "max_value",
        ):
            row[key] = _to_float(row.get(key))
        row["sample_size"] = int(row.get("sample_size") or 0)
        percentiles.append(row)
    detail["percentiles"] = percentiles

    raw = detail.get("raw")
    if not isinstance(raw, dict):
        raw = {}
    tracker = raw.get("etf_fund")
    detail["tracker_etf_codes"] = (
        [str(code) for code in tracker] if isinstance(tracker, list) else []
    )
    constituents = raw.get("stock_list")
    detail["constituents"] = (
        constituents if isinstance(constituents, list) else []
    )
    return detail


def get_index_history(
    conn: psycopg.Connection,
    index_code: str,
    metric: str,
    window: str,
) -> list[dict]:
    """历史序列（按最新分位口径的数据源），``window`` 仅接受 5y/10y/all。"""
    if window not in PERCENTILE_WINDOWS:
        raise ValueError(f"unsupported window: {window!r}")
    if metric not in SERIES_METRICS:
        raise ValueError(f"unsupported metric: {metric!r}")

    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT d.calc_src
            FROM bp_index_valuation_daily d
            WHERE d.index_code = %s AND d.is_primary
            ORDER BY d.trade_date DESC
            LIMIT 1
            """,
            (index_code,),
        )
        source_row = cur.fetchone()
        calc_src = source_row[0] if source_row else None
        if calc_src is None:
            cur.execute(
                """
                SELECT calc_src
                FROM bp_index_valuation_series
                WHERE index_code = %s AND metric = %s
                ORDER BY trade_date DESC
                LIMIT 1
                """,
                (index_code, metric),
            )
            source_row = cur.fetchone()
            calc_src = source_row[0] if source_row else None
        if calc_src is None:
            return []

        cur.execute(
            """
            SELECT trade_date, value, is_weekly, calc_src
            FROM bp_index_valuation_series
            WHERE index_code = %s AND metric = %s AND calc_src = %s
            ORDER BY trade_date
            """,
            (index_code, metric, calc_src),
        )
        raw_rows = cur.fetchall()

    if not raw_rows:
        return []

    end = raw_rows[-1][0]
    start = None
    _history_years = {"1y": 1, "3y": 3, "5y": 5, "10y": 10}
    if window in _history_years:
        start = _shift_years(end, -_history_years[window])

    result: list[dict] = []
    for trade_date, value, is_weekly, source in raw_rows:
        if start is not None and trade_date < start:
            continue
        number = _to_float(value)
        if number is None:
            continue
        result.append(
            {
                "trade_date": trade_date,
                "value": number,
                "is_weekly": bool(is_weekly),
                "calc_src": source,
            }
        )
    return result


# ---------------------------------------------------------------------------
# P1: 成分股 / 跟踪基金
# ---------------------------------------------------------------------------


def upsert_stock_master(conn: psycopg.Connection, rows: list[dict]) -> int:
    """写入股票主数据（仅身份字段，不覆盖行业等人工维护字段）。"""
    if not rows:
        return 0
    sql = """
        INSERT INTO bp_stock_master (stock_code, market, name)
        VALUES (%(stock_code)s, %(market)s, %(name)s)
        ON CONFLICT (stock_code) DO UPDATE SET
            market = EXCLUDED.market,
            name = EXCLUDED.name,
            updated_at = now()
    """
    with conn.cursor() as cur:
        cur.executemany(sql, rows)
    return len(rows)


def upsert_constituents(conn: psycopg.Connection, rows: list[dict]) -> int:
    """写入某指数某生效日的成分股权重（幂等）。"""
    if not rows:
        return 0
    sql = """
        INSERT INTO bp_index_constituent
            (index_code, effective_date, stock_code, weight, rank, source)
        VALUES (%(index_code)s, %(effective_date)s, %(stock_code)s, %(weight)s, %(rank)s, %(source)s)
        ON CONFLICT (index_code, effective_date, stock_code) DO UPDATE SET
            weight = EXCLUDED.weight,
            rank = EXCLUDED.rank,
            source = EXCLUDED.source,
            captured_at = now()
    """
    with conn.cursor() as cur:
        cur.executemany(sql, rows)
    return len(rows)


def upsert_fund_master(conn: psycopg.Connection, rows: list[dict]) -> int:
    if not rows:
        return 0
    sql = """
        INSERT INTO bp_fund_master (
            fund_code, name, company_name, risk_grade,
            manager, fund_type, management_fee, custody_fee, established_date, fund_scale
        )
        VALUES (
            %(fund_code)s, %(name)s, %(company_name)s, %(risk_grade)s,
            %(manager)s, %(fund_type)s, %(management_fee)s, %(custody_fee)s,
            %(established_date)s, %(fund_scale)s
        )
        ON CONFLICT (fund_code) DO UPDATE SET
            name = EXCLUDED.name,
            company_name = COALESCE(EXCLUDED.company_name, bp_fund_master.company_name),
            risk_grade = COALESCE(EXCLUDED.risk_grade, bp_fund_master.risk_grade),
            manager = COALESCE(EXCLUDED.manager, bp_fund_master.manager),
            fund_type = COALESCE(EXCLUDED.fund_type, bp_fund_master.fund_type),
            management_fee = COALESCE(EXCLUDED.management_fee, bp_fund_master.management_fee),
            custody_fee = COALESCE(EXCLUDED.custody_fee, bp_fund_master.custody_fee),
            established_date = COALESCE(EXCLUDED.established_date, bp_fund_master.established_date),
            fund_scale = COALESCE(EXCLUDED.fund_scale, bp_fund_master.fund_scale),
            updated_at = now()
    """
    with conn.cursor() as cur:
        cur.executemany(sql, rows)
    return len(rows)


def upsert_fund_performance(conn: psycopg.Connection, rows: list[dict]) -> int:
    """写入基金业绩与规模（按 fund_code + as_of 幂等）。"""
    if not rows:
        return 0
    sql = """
        INSERT INTO bp_fund_performance (
            fund_code, as_of, aum, ret_1m, ret_3m, ret_6m, ret_12m,
            ret_2y, ret_3y, ret_5y, ytd, manager
        ) VALUES (
            %(fund_code)s, %(as_of)s, %(aum)s, %(ret_1m)s, %(ret_3m)s, %(ret_6m)s, %(ret_12m)s,
            %(ret_2y)s, %(ret_3y)s, %(ret_5y)s, %(ytd)s, %(manager)s
        )
        ON CONFLICT (fund_code, as_of) DO UPDATE SET
            aum = COALESCE(EXCLUDED.aum, bp_fund_performance.aum),
            ret_1m = COALESCE(EXCLUDED.ret_1m, bp_fund_performance.ret_1m),
            ret_3m = COALESCE(EXCLUDED.ret_3m, bp_fund_performance.ret_3m),
            ret_6m = COALESCE(EXCLUDED.ret_6m, bp_fund_performance.ret_6m),
            ret_12m = COALESCE(EXCLUDED.ret_12m, bp_fund_performance.ret_12m),
            ret_2y = COALESCE(EXCLUDED.ret_2y, bp_fund_performance.ret_2y),
            ret_3y = COALESCE(EXCLUDED.ret_3y, bp_fund_performance.ret_3y),
            ret_5y = COALESCE(EXCLUDED.ret_5y, bp_fund_performance.ret_5y),
            ytd = COALESCE(EXCLUDED.ytd, bp_fund_performance.ytd),
            manager = COALESCE(EXCLUDED.manager, bp_fund_performance.manager),
            captured_at = now()
    """
    with conn.cursor() as cur:
        cur.executemany(sql, rows)
    return len(rows)


def compare_funds(
    conn: psycopg.Connection,
    fund_codes: list[str],
    start: date | None = None,
    end: date | None = None,
    benchmark_code: str = "000300",
) -> dict:
    """基金对比：区间总收益/年化收益/波动/最大回撤 + 相对基准的跟踪误差与信息比率。"""
    import math

    if not fund_codes:
        return {"start": None, "end": None, "benchmark_code": benchmark_code, "items": []}
    end = end or date.today()
    start = start or date(end.year, 1, 1)
    with conn.cursor() as cur:
        cur.execute(
            "SELECT fund_code, trade_date, nav FROM bp_fund_nav_daily"
            " WHERE fund_code = ANY(%s) AND trade_date BETWEEN %s AND %s"
            " ORDER BY fund_code, trade_date",
            (fund_codes, start, end),
        )
        rows = cur.fetchall()
        cur.execute(
            "SELECT fund_code, name, fund_scale FROM bp_fund_master WHERE fund_code = ANY(%s)",
            (fund_codes,),
        )
        meta = {row[0]: {"name": row[1], "fund_scale": row[2]} for row in cur.fetchall()}
        cur.execute(
            "SELECT symbol, trade_date, close FROM bp_index_quote_daily"
            " WHERE symbol = %s AND adjust = 'bfq' AND trade_date BETWEEN %s AND %s ORDER BY trade_date",
            (benchmark_code, start, end),
        )
        bench_rows = cur.fetchall()
    bench_map: dict = {}
    for row in bench_rows:
        if row[2] is None:
            continue
        bench_map[pd.Timestamp(row[1])] = float(row[2])
    bench = pd.Series(bench_map).sort_index()
    frame = pd.DataFrame(rows, columns=["fund_code", "trade_date", "nav"])
    items = []
    for fund_code, part in frame.groupby("fund_code"):
        series = pd.Series(
            pd.to_numeric(part["nav"], errors="coerce").to_numpy(),
            index=pd.to_datetime(part["trade_date"]),
        ).dropna().sort_index()
        if len(series) < 5:
            continue
        total = float(series.iloc[-1] / series.iloc[0] - 1)
        days = max((series.index[-1] - series.index[0]).days, 1)
        ann = (1 + total) ** (365.0 / days) - 1
        rets = series.pct_change().dropna()
        vol = float(rets.std() * math.sqrt(252))
        cummax = series.cummax()
        mdd = float((series / cummax - 1).min())
        item = {
            "fund_code": fund_code,
            "name": (meta.get(fund_code) or {}).get("name"),
            "fund_scale": float((meta.get(fund_code) or {}).get("fund_scale")) if (meta.get(fund_code) or {}).get("fund_scale") is not None else None,
            "start": str(series.index[0].date()),
            "end": str(series.index[-1].date()),
            "n_obs": int(len(series)),
            "total_return_pct": round(total * 100, 4),
            "ann_return_pct": None if days < 30 else round(ann * 100, 4),
            "ann_vol_pct": round(vol * 100, 4),
            "max_dd_pct": round(mdd * 100, 4),
        }
        bench_aligned = bench.reindex(series.index, method="ffill")
        bench_ret = bench_aligned.pct_change().dropna()
        joined = pd.concat([rets.rename("fund"), bench_ret.rename("bench")], axis=1).dropna()
        if len(joined) > 20:
            diff = joined["fund"] - joined["bench"]
            te = float(diff.std() * math.sqrt(252))
            bench_total = float((1 + joined["bench"]).prod())
            bench_ann = bench_total ** (365.0 / max(days, 1)) - 1 if days else None
            item["tracking_error_pct"] = round(te * 100, 4)
            item["info_ratio"] = round((ann - bench_ann) / te, 4) if te > 1e-9 and bench_ann is not None else None
            item["excess_return_pct"] = round((total - (bench_total - 1)) * 100, 4)
        else:
            item["tracking_error_pct"] = None
            item["info_ratio"] = None
            item["excess_return_pct"] = None
        items.append(item)
    items.sort(key=lambda row: row["total_return_pct"], reverse=True)
    return {
        "start": str(start),
        "end": str(end),
        "benchmark_code": benchmark_code,
        "items": items,
    }


BENCHMARK_HISTOGRAM_BINS = 30
HISTOGRAM_MIN_OBS = 10


def build_return_histograms(
    target_returns: Any,
    benchmark_returns: Any,
    bins: int = BENCHMARK_HISTOGRAM_BINS,
) -> tuple[list[dict], list[dict]]:
    """指数 / 基准日收益直方图：同一时间窗口 + 公共 bins，保证前端双系列可对比。

    - 入参是同一收益窗口（近 1 年日收益，百分数点前的小数收益）；
    - 公共 bins 由两者合并后的取值范围决定，两侧 bin 中心完全一致；
    - 样本不足（<= HISTOGRAM_MIN_OBS）或全为 NaN 时返回两个空列表，绝不构造数据。

    返回 (histogram, benchmark_histogram)，元素形如 {"bin": 中心值%, "count": 天数}。
    """
    target = np.asarray(pd.Series(target_returns).dropna(), dtype=float) * 100.0
    bench = np.asarray(pd.Series(benchmark_returns).dropna(), dtype=float) * 100.0
    target = target[np.isfinite(target)]
    bench = bench[np.isfinite(bench)]
    if len(target) <= HISTOGRAM_MIN_OBS or len(bench) <= HISTOGRAM_MIN_OBS:
        return [], []
    edges = np.histogram_bin_edges(np.concatenate([target, bench]), bins=bins)
    target_counts, _ = np.histogram(target, bins=edges)
    bench_counts, _ = np.histogram(bench, bins=edges)
    centers = [
        round(float((edges[index] + edges[index + 1]) / 2.0), 3)
        for index in range(len(edges) - 1)
    ]
    histogram = [
        {"bin": centers[index], "count": int(target_counts[index])}
        for index in range(len(centers))
    ]
    benchmark_histogram = [
        {"bin": centers[index], "count": int(bench_counts[index])}
        for index in range(len(centers))
    ]
    return histogram, benchmark_histogram


def get_index_benchmark_stats(
    conn: psycopg.Connection, index_code: str, benchmark_code: str = "000300"
) -> dict:
    """指数 vs 基准的日收益描述统计（直方图 + Beta + 相关系数）。"""
    import math

    with conn.cursor() as cur:
        cur.execute(
            "SELECT symbol, trade_date, close FROM bp_index_quote_daily"
            " WHERE symbol IN (%s, %s) AND adjust = 'bfq' ORDER BY symbol, trade_date",
            (index_code, benchmark_code),
        )
        rows = cur.fetchall()
        cur.execute("SELECT name FROM bp_index_master WHERE index_code = %s", (benchmark_code,))
        name_row = cur.fetchone()
    if not rows:
        return {}
    frame = pd.DataFrame(rows, columns=["symbol", "trade_date", "close"])
    frame["trade_date"] = pd.to_datetime(frame["trade_date"])
    frame["close"] = pd.to_numeric(frame["close"], errors="coerce")
    frame = frame.drop_duplicates(subset=["symbol", "trade_date"], keep="last")
    wide = frame.pivot(index="trade_date", columns="symbol", values="close").dropna()
    if index_code not in wide or benchmark_code not in wide or len(wide) < 60:
        return {}
    rets = wide.pct_change().dropna()
    target = rets[index_code]
    bench = rets[benchmark_code]
    tail = rets.iloc[-757:] if len(rets) > 757 else rets
    vol = float(tail[index_code].std() * math.sqrt(252))
    beta = None
    if len(tail) > 5:
        cov = float(np.cov(tail[index_code], tail[benchmark_code])[0][1])
        var = float(np.var(tail[benchmark_code], ddof=1))
        beta = cov / var if var > 1e-12 else None
    pearson = float(tail[index_code].corr(tail[benchmark_code]))
    rank_idx = tail[index_code].rank()
    rank_bench = tail[benchmark_code].rank()
    spearman = float(rank_idx.corr(rank_bench))
    window = target.iloc[-252:] if len(target) > 252 else target
    # 基准取同一批交易日的收益（target/bench 来自同一 wide 面板，索引一致），
    # 与指数共用公共 bins，前端才能把两条分布叠在同一 x 轴上对比。
    bench_window = bench.reindex(window.index)
    histogram, benchmark_histogram = build_return_histograms(window, bench_window)
    mean = float(window.mean() * 100)
    std = float(window.std() * 100)
    skew = None
    kurt = None
    if len(window) > 2 and std > 1e-12:
        skew = float((((window - window.mean()) ** 3).mean()) / ((window.std()) ** 3))
    if len(window) > 3 and std > 1e-12:
        kurt = float((((window - window.mean()) ** 4).mean()) / ((window.std()) ** 4) - 3)
    return {
        "index_code": index_code,
        "benchmark_code": benchmark_code,
        "benchmark_name": name_row[0] if name_row else benchmark_code,
        "as_of": str(wide.index[-1].date()),
        "n_obs": int(len(window)),
        "ann_vol": round(vol * 100, 4),
        "beta": None if beta is None else round(beta, 4),
        "pearson": round(pearson, 4),
        "spearman": round(spearman, 4),
        "mean_daily_pct": round(mean, 4),
        "std_daily_pct": round(std, 4),
        "skew": None if skew is None else round(skew, 3),
        "kurtosis": None if kurt is None else round(kurt, 3),
        "histogram": histogram,
        # 同窗口/公共 bins 的基准直方图；样本不足时为空数组（前端退回单系列）。
        "benchmark_histogram": benchmark_histogram,
    }


def upsert_market_valuation_index(conn: psycopg.Connection, rows: list[dict]) -> int:
    """写入 MVI 时间序列（按 as_of 幂等）。"""
    if not rows:
        return 0
    sql = """
        INSERT INTO bp_market_valuation_index (
            as_of, mvi, cheap_score, risk_score, zone,
            factors, weights, contributions, risk_factors
        ) VALUES (
            %(as_of)s, %(mvi)s, %(cheap_score)s, %(risk_score)s, %(zone)s,
            %(factors)s, %(weights)s, %(contributions)s, %(risk_factors)s
        )
        ON CONFLICT (as_of) DO UPDATE SET
            mvi = EXCLUDED.mvi,
            cheap_score = EXCLUDED.cheap_score,
            risk_score = EXCLUDED.risk_score,
            zone = EXCLUDED.zone,
            factors = EXCLUDED.factors,
            weights = EXCLUDED.weights,
            contributions = EXCLUDED.contributions,
            risk_factors = EXCLUDED.risk_factors,
            updated_at = now()
    """
    records: list[dict] = []
    for row in rows:
        item = dict(row)
        for key in ("factors", "weights", "contributions", "risk_factors"):
            value = item.get(key)
            if value is not None and not isinstance(value, str):
                item[key] = _json_value(value)
        records.append(item)
    with conn.cursor() as cur:
        cur.executemany(sql, records)
    return len(records)


def get_market_valuation_index(conn: psycopg.Connection, history_limit: int = 160) -> dict:
    """返回最新 MVI + 最近 history_limit 个点（周频）。"""
    with conn.cursor() as cur:
        cur.execute(
            "SELECT as_of, mvi, cheap_score, risk_score, zone, factors, weights, contributions, risk_factors"
            " FROM bp_market_valuation_index ORDER BY as_of DESC LIMIT 1"
        )
        row = cur.fetchone()
        columns = [desc.name for desc in cur.description] if cur.description else []
        latest = dict(zip(columns, row)) if row else None
        cur.execute(
            "SELECT as_of, mvi, risk_score FROM bp_market_valuation_index ORDER BY as_of DESC LIMIT %s",
            (history_limit,),
        )
        history = [
            {"as_of": item[0].isoformat() if hasattr(item[0], "isoformat") else str(item[0]),
             "mvi": float(item[1]) if item[1] is not None else None,
             "risk": float(item[2]) if item[2] is not None else None}
            for item in cur.fetchall()
        ]
    if latest:
        for key in ("mvi", "cheap_score", "risk_score"):
            latest[key] = float(latest[key]) if latest.get(key) is not None else None
        latest["as_of"] = latest["as_of"].isoformat() if hasattr(latest["as_of"], "isoformat") else str(latest["as_of"])
        history.reverse()
    return {"latest": latest, "history": history}


def upsert_quote_health(conn: psycopg.Connection, rows: list[dict]) -> int:
    """写入指数行情覆盖率看护结果。"""
    if not rows:
        return 0
    sql = """
        INSERT INTO bp_index_quote_health (
            symbol, last_trade_date, expected_trade_date, lag_trading_days, has_quote, status, checked_at
        ) VALUES (
            %(symbol)s, %(last_trade_date)s, %(expected_trade_date)s,
            %(lag_trading_days)s, %(has_quote)s, %(status)s, now()
        )
        ON CONFLICT (symbol) DO UPDATE SET
            last_trade_date = EXCLUDED.last_trade_date,
            expected_trade_date = EXCLUDED.expected_trade_date,
            lag_trading_days = EXCLUDED.lag_trading_days,
            has_quote = EXCLUDED.has_quote,
            status = EXCLUDED.status,
            checked_at = now()
    """
    with conn.cursor() as cur:
        cur.executemany(sql, rows)
    return len(rows)


def upsert_tracker_funds(conn: psycopg.Connection, rows: list[dict]) -> int:
    if not rows:
        return 0
    sql = """
        INSERT INTO bp_index_tracker_fund
            (index_code, fund_code, trade_date, aum, source)
        VALUES (%(index_code)s, %(fund_code)s, %(trade_date)s, %(aum)s, %(source)s)
        ON CONFLICT (index_code, fund_code, trade_date) DO UPDATE SET
            aum = EXCLUDED.aum,
            source = EXCLUDED.source,
            captured_at = now()
    """
    with conn.cursor() as cur:
        cur.executemany(sql, rows)
    return len(rows)


def get_index_constituents(
    conn: psycopg.Connection, index_code: str, limit: int = 60
) -> list[dict]:
    """最新生效日的成分股权重（前 N 大）。"""
    sql = """
        WITH latest AS (
            SELECT max(effective_date) AS d
            FROM bp_index_constituent WHERE index_code = %(code)s
        )
        SELECT c.stock_code, COALESCE(s.name, c.stock_code) AS name,
               s.industry_l1, c.weight, c.rank, c.effective_date, c.source
        FROM bp_index_constituent c
        LEFT JOIN bp_stock_master s USING (stock_code)
        WHERE c.index_code = %(code)s AND c.effective_date = (SELECT d FROM latest)
        ORDER BY c.rank NULLS LAST, c.weight DESC NULLS LAST
        LIMIT %(limit)s
    """
    with conn.cursor() as cur:
        cur.execute(sql, {"code": index_code, "limit": max(1, int(limit))})
        columns = [desc.name for desc in cur.description]
        records = cur.fetchall()
    out: list[dict] = []
    for record in records:
        item = dict(zip(columns, record))
        item["weight"] = _to_float(item.get("weight"))
        item["rank"] = _to_int(item.get("rank"))
        out.append(item)
    return out


def get_index_tracker_funds(
    conn: psycopg.Connection, index_code: str
) -> list[dict]:
    """最新交易日的跟踪基金：规模 + 费率 + 成立日 + 各期业绩。"""
    sql = """
        WITH latest AS (
            SELECT max(trade_date) AS d
            FROM bp_index_tracker_fund WHERE index_code = %(code)s
        ), meta AS (
            SELECT max(trade_date) AS data_as_of, max(captured_at) AS updated_at
            FROM bp_index_tracker_fund WHERE index_code = %(code)s
        ), risk_meta AS (
            SELECT max(r.updated_at) AS risk_updated_at
            FROM bp_index_tracker_fund t
            JOIN bp_fund_risk r USING (fund_code)
            WHERE t.index_code = %(code)s
        )
        SELECT t.fund_code, COALESCE(f.name, t.fund_code) AS name,
               f.company_name, f.risk_grade, t.aum, t.trade_date,
               f.manager, f.fund_type, f.management_fee, f.custody_fee,
               f.established_date, f.fund_scale,
               p.ret_1m, p.ret_3m, p.ret_6m, p.ret_12m,
               p.ret_2y, p.ret_3y, p.ret_5y, p.ytd,
               r.ann_vol_1y, r.max_dd_1y, r.tracking_error_1y, r.info_ratio_1y,
               r.ret_3y_ann AS risk_ret_3y_ann, r.ret_5y_ann AS risk_ret_5y_ann,
               meta.data_as_of, meta.updated_at, risk_meta.risk_updated_at
        FROM bp_index_tracker_fund t
        CROSS JOIN meta
        CROSS JOIN risk_meta
        LEFT JOIN bp_fund_master f USING (fund_code)
        LEFT JOIN LATERAL (
            SELECT * FROM bp_fund_performance perf
            WHERE perf.fund_code = t.fund_code
            ORDER BY perf.as_of DESC
            LIMIT 1
        ) p ON TRUE
        LEFT JOIN bp_fund_risk r ON r.fund_code = t.fund_code
        WHERE t.index_code = %(code)s AND t.trade_date = (SELECT d FROM latest)
        ORDER BY t.aum DESC NULLS LAST
    """
    with conn.cursor() as cur:
        cur.execute(sql, {"code": index_code})
        columns = [desc.name for desc in cur.description]
        records = cur.fetchall()
    out: list[dict] = []
    for record in records:
        item = dict(zip(columns, record))
        for key in (
            "aum", "management_fee", "custody_fee", "fund_scale",
            "ret_1m", "ret_3m", "ret_6m", "ret_12m", "ret_2y", "ret_3y", "ret_5y", "ytd",
            "ann_vol_1y", "max_dd_1y", "tracking_error_1y", "info_ratio_1y",
            "risk_ret_3y_ann", "risk_ret_5y_ann",
        ):
            item[key] = _to_float(item.get(key))
        out.append(item)
    return out


# ---------------------------------------------------------------------------
# 估值最新快照（ddl/80 bp_index_valuation_latest）：刷新 + 快速读取
# ---------------------------------------------------------------------------

# 5 个分位窗口（与 bp_index_percentile.ck_pct_window 一致）
LATEST_WINDOWS = ("1y", "3y", "5y", "10y", "all")
# 快照刷新时 sparkline 取最近多少天（约 1 年）
SPARK_DAYS = 365
# 52 周涨跌/位置的行情观察下限（与旧 get_index_list 一致：>=200 个交易日才宣称 52 周）
QUOTE_52W_MIN_OBS = 200


def _window_percentile(
    percentiles: dict, metric: str, window: str
) -> Optional[float]:
    """从快照 percentiles JSONB 取某指标某窗口的分位。"""
    item = percentiles.get(metric) if isinstance(percentiles, dict) else None
    if isinstance(item, dict):
        return _to_float(item.get(window))
    return None


def _spark_series(rows: list[tuple[date, float]]) -> list[list[Any]]:
    """把日/周频点压缩成周频 sparkline：每 ISO 周保留最后一个点，最多 60 个点。"""
    weekly: dict[tuple[int, int], tuple[date, float]] = {}
    for trade_date, value in rows:
        iso = trade_date.isocalendar()
        weekly[(iso[0], iso[1])] = (trade_date, value)
    points = [
        [day.isoformat(), round(value, 6)]
        for _, (day, value) in sorted(weekly.items(), key=lambda item: item[1][0])
    ]
    return points[-60:]




def refresh_quote_health_from_quotes(
    conn: psycopg.Connection,
    quotes: dict[str, list[tuple[date, float]]],
) -> int:
    """用本次快照刷新已读取的 bfq 行情 + 交易日历批量校准 bp_index_quote_health。

    背景：行情补数（index_quotes_free / repair_quote_clean）可能晚于行情健康看护任务
    写库；旧的 quote_health 一旦写入就不会自动更新，列表会把「行情已补齐」的指数
    持续误标为 stale。这里在估值快照刷新收尾时用同一批行情重算，health 与最新行情
    保持一致。单条日历区间查询 + 内存计 lag，不给每个指数单独发 SQL。

    ddl/79 之前的库没有 bp_index_quote_health 表时静默跳过（不影响快照刷新）。
    """
    if not quotes:
        return 0
    last_dates = {
        code: points[-1][0]
        for code, points in quotes.items()
        if points and points[-1][0] is not None
    }
    if not last_dates:
        return 0
    try:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT max(cal_date) FROM bp_trading_calendar"
                " WHERE is_trading AND cal_date <= current_date"
            )
            row = cur.fetchone()
            expected = row[0] if row else None
            if expected is not None:
                cur.execute(
                    "SELECT cal_date FROM bp_trading_calendar"
                    " WHERE is_trading AND cal_date > %s AND cal_date <= %s"
                    " ORDER BY cal_date",
                    (min(last_dates.values()), expected),
                )
                trading_days = [item[0] for item in cur.fetchall()]
            else:
                trading_days = []
        rows: list[dict] = []
        for code, last_date in last_dates.items():
            if expected is None or last_date >= expected:
                lag = 0
                status = "ok"
            else:
                lag = sum(1 for day in trading_days if day > last_date)
                status = "stale" if lag <= 5 else "dead"
            rows.append(
                {
                    "symbol": code,
                    "last_trade_date": last_date,
                    "expected_trade_date": expected,
                    "lag_trading_days": lag,
                    "has_quote": True,
                    "status": status,
                }
            )
        return upsert_quote_health(conn, rows)
    except psycopg.errors.UndefinedTable:
        # 旧库（ddl/79 未应用）没有交易日历/health 表：跳过，不影响估值快照。
        return 0


def refresh_valuation_latest(
    conn: psycopg.Connection,
    window_key: str = "5y",
    index_codes: Optional[list[str]] = None,
    spark_days: int = SPARK_DAYS,
) -> int:
    """全量/增量刷新 bp_index_valuation_latest，返回写入行数。

    由估值任务收尾调用（bp_ingest.valuation_ingest.run_valuation_ingest 末尾）。
    纯读请求路径不调用本函数。

    刷新内容（每指数 1 行）：
      - 最新 is_primary 估值日 4 指标当前值 + calc_src 口径标记；
      - 4 指标 x 5 窗口预计算分位（percentiles JSONB）+ 5y 扁平列；
      - 最近 1 年周频 sparkline（pe_spark JSONB，4 指标）；
      - 行情预计算：最新收盘/1 日涨跌/52 周涨跌/52 周位置（bp_index_quote_daily bfq）；
      - coverage_start（主口径估值序列最早日期）。

    单个指数的行情/分位缺失都写 NULL，不插值、不造数。
    """
    window = window_key if window_key in PERCENTILE_WINDOWS else "5y"
    spark_days = max(30, int(spark_days))
    code_filter = ""
    params: list[Any] = []
    if index_codes is not None:
        codes = [str(code) for code in index_codes if code]
        if not codes:
            return 0
        code_filter = " AND d.index_code = ANY(%s)"
        params.append(codes)

    with conn.cursor() as cur:
        # 1) 每个指数最新一条主口径估值
        cur.execute(
            """
            SELECT DISTINCT ON (d.index_code)
                   d.index_code, d.trade_date, d.calc_src, d.is_primary,
                   d.pe_ttm, d.pb, d.dividend_yield_ttm, d.erp, d.roe_ttm
            FROM bp_index_valuation_daily d
            WHERE d.is_primary
            """
            + code_filter
            + """
            ORDER BY d.index_code, d.trade_date DESC
            """,
            params,
        )
        daily_rows = cur.fetchall()

    if not daily_rows:
        return 0

    codes = [row[0] for row in daily_rows]
    latest_by_code: dict[str, dict] = {}
    for (
        index_code,
        trade_date,
        calc_src,
        is_primary,
        pe_ttm,
        pb,
        dividend_yield_ttm,
        erp,
        roe_ttm,
    ) in daily_rows:
        latest_by_code[index_code] = {
            "index_code": index_code,
            "trade_date": trade_date,
            "calc_src": calc_src,
            "is_primary": bool(is_primary),
            "pe_ttm": pe_ttm,
            "pb": pb,
            "dividend_yield_ttm": dividend_yield_ttm,
            "erp": erp,
            # ROE 快照列（ddl/81）：ROE×PE 矩阵数据源，缺失写 NULL 不造数。
            "roe_ttm": roe_ttm,
        }

    with conn.cursor() as cur:
        # 2) 多窗口分位（只取各指数最新 as_of 的那一批，且口径与日频一致）
        cur.execute(
            """
            WITH latest_daily AS (
                SELECT DISTINCT ON (index_code) index_code, calc_src
                FROM bp_index_valuation_daily
                WHERE is_primary AND index_code = ANY(%s)
                ORDER BY index_code, trade_date DESC
            )
            SELECT DISTINCT ON (p.index_code, p.metric, p.window_key)
                   p.index_code, p.metric, p.window_key, p.pct
            FROM bp_index_percentile p
            JOIN latest_daily ld USING (index_code)
            WHERE p.calc_src = ld.calc_src
            ORDER BY p.index_code, p.metric, p.window_key, p.as_of_date DESC
            """,
            (codes,),
        )
        percentile_rows = cur.fetchall()

        # 3) coverage_start = 主口径估值序列最早日期
        cur.execute(
            """
            WITH latest_daily AS (
                SELECT DISTINCT ON (index_code) index_code, calc_src
                FROM bp_index_valuation_daily
                WHERE is_primary AND index_code = ANY(%s)
                ORDER BY index_code, trade_date DESC
            )
            SELECT s.index_code, min(s.trade_date)
            FROM bp_index_valuation_series s
            JOIN latest_daily ld ON ld.index_code = s.index_code AND ld.calc_src = s.calc_src
            GROUP BY s.index_code
            """,
            (codes,),
        )
        coverage_rows = cur.fetchall()

        # 4) sparkline：最近 1 年（相对各指数最新估值日）4 指标序列
        cur.execute(
            """
            WITH latest_daily AS (
                SELECT DISTINCT ON (index_code) index_code, calc_src, trade_date
                FROM bp_index_valuation_daily
                WHERE is_primary AND index_code = ANY(%s)
                ORDER BY index_code, trade_date DESC
            )
            SELECT s.index_code, s.metric, s.trade_date, s.value
            FROM bp_index_valuation_series s
            JOIN latest_daily ld
              ON ld.index_code = s.index_code AND ld.calc_src = s.calc_src
            WHERE s.metric = ANY(%s)
              AND s.trade_date >= ld.trade_date - (%s || ' days')::interval
            ORDER BY s.index_code, s.metric, s.trade_date
            """,
            (codes, list(SERIES_METRICS), str(spark_days)),
        )
        spark_rows = cur.fetchall()

        # 5) 行情预计算：最近 400 天收盘（去重：同 (symbol,date) 多源时取最新更新的一行）
        cur.execute(
            """
            SELECT DISTINCT ON (symbol, trade_date)
                   symbol, trade_date, close
            FROM bp_index_quote_daily
            WHERE adjust = 'bfq' AND close IS NOT NULL
              AND symbol = ANY(%s)
              AND trade_date >= current_date - 400
            ORDER BY symbol, trade_date, updated_at DESC,
                CASE source
                    WHEN 'csindex_perf' THEN 0
                    WHEN 'cn_index_em' THEN 1
                    WHEN 'cn_index_sina' THEN 2
                    ELSE 9
                END
            """,
            (codes,),
        )
        quote_rows = cur.fetchall()

    percentiles: dict[str, dict[str, dict[str, Optional[float]]]] = {}
    for index_code, metric, window_key, pct in percentile_rows:
        percentiles.setdefault(index_code, {}).setdefault(metric, {})[window_key] = _to_float(pct)

    coverage: dict[str, Optional[date]] = {
        index_code: trade_date for index_code, trade_date in coverage_rows
    }

    spark_raw: dict[str, dict[str, list[tuple[date, float]]]] = {}
    for index_code, metric, trade_date, value in spark_rows:
        number = _to_float(value)
        if trade_date is None or number is None:
            continue
        spark_raw.setdefault(index_code, {}).setdefault(metric, []).append(
            (trade_date, number)
        )

    quotes: dict[str, list[tuple[date, float]]] = {}
    for symbol, trade_date, close in quote_rows:
        number = _to_float(close)
        if trade_date is None or number is None:
            continue
        quotes.setdefault(symbol, []).append((trade_date, number))

    records: list[tuple] = []
    for index_code, item in latest_by_code.items():
        metric_pct = percentiles.get(index_code, {})
        spark_payload = {
            metric: _spark_series(points)
            for metric, points in spark_raw.get(index_code, {}).items()
            if points
        }
        flat = {
            metric: _window_percentile(metric_pct, metric, window)
            for metric in ("pe_ttm", "pb", "dividend_yield_ttm", "erp")
        }

        close_price = None
        change_pct = None
        change_52w_pct = None
        position_52w_pct = None
        price_trade_date = None
        points = quotes.get(index_code) or []
        if points:
            points.sort(key=lambda point: point[0])
            price_trade_date = points[-1][0]
            close_price = points[-1][1]
            if len(points) >= 2 and points[-2][1]:
                change_pct = (close_price / points[-2][1] - 1.0) * 100.0
            if len(points) >= QUOTE_52W_MIN_OBS:
                high = max(value for _, value in points)
                low = min(value for _, value in points)
                if len(points) > 252:
                    base = points[-252][1]
                    if base:
                        change_52w_pct = (close_price / base - 1.0) * 100.0
                if high > low:
                    position_52w_pct = (close_price - low) / (high - low) * 100.0

        records.append(
            (
                index_code,
                item["trade_date"],
                item["calc_src"],
                item["is_primary"],
                _to_float(item["pe_ttm"]),
                _to_float(item["pb"]),
                _to_float(item["dividend_yield_ttm"]),
                _to_float(item["erp"]),
                _to_float(item.get("roe_ttm")),
                flat["pe_ttm"],
                flat["pb"],
                flat["dividend_yield_ttm"],
                flat["erp"],
                _json_value(metric_pct or None),
                _json_value(spark_payload or None),
                close_price,
                change_pct,
                change_52w_pct,
                position_52w_pct,
                price_trade_date,
                coverage.get(index_code),
            )
        )

    sql = """
        INSERT INTO bp_index_valuation_latest (
            index_code, trade_date, calc_src, is_primary,
            pe_ttm, pb, dividend_yield_ttm, erp, roe_ttm,
            pe_percentile, pb_percentile, dividend_percentile, erp_percentile,
            percentiles, pe_spark,
            close_price, change_pct, change_52w_pct, position_52w_pct,
            price_trade_date, coverage_start
        ) VALUES (
            %s, %s, %s, %s,
            %s, %s, %s, %s, %s,
            %s, %s, %s, %s,
            %s, %s,
            %s, %s, %s, %s,
            %s, %s
        )
        ON CONFLICT (index_code) DO UPDATE SET
            trade_date = EXCLUDED.trade_date,
            calc_src = EXCLUDED.calc_src,
            is_primary = EXCLUDED.is_primary,
            pe_ttm = EXCLUDED.pe_ttm,
            pb = EXCLUDED.pb,
            dividend_yield_ttm = EXCLUDED.dividend_yield_ttm,
            erp = EXCLUDED.erp,
            roe_ttm = EXCLUDED.roe_ttm,
            pe_percentile = EXCLUDED.pe_percentile,
            pb_percentile = EXCLUDED.pb_percentile,
            dividend_percentile = EXCLUDED.dividend_percentile,
            erp_percentile = EXCLUDED.erp_percentile,
            percentiles = EXCLUDED.percentiles,
            pe_spark = EXCLUDED.pe_spark,
            close_price = EXCLUDED.close_price,
            change_pct = EXCLUDED.change_pct,
            change_52w_pct = EXCLUDED.change_52w_pct,
            position_52w_pct = EXCLUDED.position_52w_pct,
            price_trade_date = EXCLUDED.price_trade_date,
            coverage_start = EXCLUDED.coverage_start,
            updated_at = now()
    """
    with conn.cursor() as cur:
        cur.executemany(sql, records)
        if index_codes is None:
            # 全量刷新时清掉已无主口径估值的指数，避免快照残留旧行
            cur.execute(
                "DELETE FROM bp_index_valuation_latest WHERE NOT (index_code = ANY(%s))",
                (codes,),
            )
    # 收尾：用本次已读取的行情批量校准 quote health（详情见函数 docstring）。
    refresh_quote_health_from_quotes(conn, quotes)
    return len(records)


def get_valuation_latest_list(
    conn: psycopg.Connection, window: str = "5y"
) -> list[dict]:
    """读取估值最新快照（一条 SQL，<50ms），返回全部指数 4 指标当前值/分位/涨跌。

    不含 sparkline（payload 控制；前端需要时用详情/历史接口）。分位按 window
    从 percentiles JSONB 取；5 个窗口都已预计算，单次响应按入参挑选一个窗口。
    """
    window = window if window in PERCENTILE_WINDOWS else "5y"
    sql = """
        SELECT
            l.index_code,
            m.name,
            m.short_name,
            m.index_type,
            m.industry,
            m.market,
            m.publisher,
            l.trade_date,
            l.calc_src,
            l.is_primary,
            l.pe_ttm,
            l.pb,
            l.dividend_yield_ttm,
            l.erp,
            l.roe_ttm,
            l.pe_percentile,
            l.pb_percentile,
            l.dividend_percentile,
            l.erp_percentile,
            l.percentiles,
            l.close_price,
            l.change_pct,
            l.change_52w_pct,
            l.position_52w_pct,
            l.price_trade_date,
            l.coverage_start,
            l.updated_at,
            fs.fund_count,
            fs.aum_sum AS fund_aum,
            h.status AS quote_status,
            h.lag_trading_days AS quote_lag_days
        FROM bp_index_valuation_latest l
        JOIN bp_index_master m ON m.index_code = l.index_code
        LEFT JOIN bp_index_fund_scale fs ON fs.index_code = l.index_code
        LEFT JOIN bp_index_quote_health h ON h.symbol = l.index_code
        ORDER BY l.index_code
    """
    with conn.cursor() as cur:
        cur.execute(sql)
        columns = [desc.name for desc in cur.description]
        records = cur.fetchall()

    numeric_fields = {
        "pe_ttm",
        "pb",
        "dividend_yield_ttm",
        "erp",
        "roe_ttm",
        "pe_percentile",
        "pb_percentile",
        "dividend_percentile",
        "erp_percentile",
        "close_price",
        "change_pct",
        "change_52w_pct",
        "position_52w_pct",
        "fund_aum",
    }
    out: list[dict] = []
    for record in records:
        item = dict(zip(columns, record))
        raw_percentiles = item.pop("percentiles", None)
        percentiles = raw_percentiles if isinstance(raw_percentiles, dict) else {}
        for key in numeric_fields:
            item[key] = _to_float(item.get(key))
        item["fund_count"] = _to_int(item.get("fund_count"))
        item["quote_lag_days"] = _to_int(item.get("quote_lag_days"))
        item["is_primary"] = bool(item.get("is_primary"))
        for metric, field in (
            ("pe_ttm", "pe_percentile"),
            ("pb", "pb_percentile"),
            ("dividend_yield_ttm", "dividend_percentile"),
            ("erp", "erp_percentile"),
        ):
            # P2：请求窗口的分位缺失时必须置 None，不能沿用 5y 扁平列（否则前端
            # 把「5y 分位」误标成所选窗口，制造假数据）。5y 也只在 JSONB 有值时才给。
            item[field] = _window_percentile(percentiles, metric, window)
        item["has_valuation"] = True
        item["window"] = window
        out.append(item)
    return out


# ---------------------------------------------------------------------------
# MVI（bp_market_valuation_index）：区间序列 / overlay
# ---------------------------------------------------------------------------

MVI_RANGES = {"1y": 1, "3y": 3, "5y": 5, "10y": 10, "all": None}
# overlay 支持 4 只宽基（需求 3：沪深300 / 中证A500 / 上证50 / 中证全指）
OVERLAY_INDEX_CODES = ("000300", "000510", "000016", "000985")


def _mvi_row(raw: tuple, columns: list[str]) -> dict:
    item = dict(zip(columns, raw))
    for key in ("mvi", "cheap_score", "risk_score"):
        item[key] = _to_float(item.get(key))
    as_of = item.get("as_of")
    item["as_of"] = as_of.isoformat() if isinstance(as_of, date) else as_of
    return item


def get_market_valuation_index_range(
    conn: psycopg.Connection, range_key: str = "5y"
) -> dict:
    """MVI 最新值 + 区间周频序列（range: 1y/3y/5y/10y/all）。"""
    years = MVI_RANGES.get(range_key, 5)
    with conn.cursor() as cur:
        cur.execute(
            "SELECT as_of, mvi, cheap_score, risk_score, zone, factors, weights,"
            " contributions, risk_factors"
            " FROM bp_market_valuation_index ORDER BY as_of DESC LIMIT 1"
        )
        row = cur.fetchone()
        columns = [desc.name for desc in cur.description] if cur.description else []
        latest = _mvi_row(row, columns) if row else None

        start = None
        if latest and years is not None:
            start = _shift_years(date.fromisoformat(latest["as_of"]), -years)

        sql = (
            "SELECT as_of, mvi, risk_score FROM bp_market_valuation_index"
            + (" WHERE as_of >= %s" if start is not None else "")
            + " ORDER BY as_of"
        )
        cur.execute(sql, (start,) if start is not None else ())
        history = [
            {
                "as_of": as_of.isoformat() if isinstance(as_of, date) else as_of,
                "mvi": _to_float(mvi),
                "risk": _to_float(risk),
            }
            for as_of, mvi, risk in cur.fetchall()
        ]
    return {"latest": latest, "history": history, "range": range_key, "start": start}


def get_market_mvi_overlay(
    conn: psycopg.Connection, index_code: str, range_key: str = "5y"
) -> dict:
    """MVI 周频序列 + 指定指数的收盘价序列（双轴图 overlay）。

    价格来源 bp_index_quote_daily（bfq，原币口径，多源同 (symbol,date) 取最新更新行）。
    指数无行情时返回 missing=True 且不造数；未知/未支持指数由 API 层 404。
    """
    years = MVI_RANGES.get(range_key, 5)
    mvi = get_market_valuation_index_range(conn, range_key)

    with conn.cursor() as cur:
        cur.execute(
            "SELECT name FROM bp_index_master WHERE index_code = %s",
            (index_code,),
        )
        name_row = cur.fetchone()

        # 价格覆盖起点（全历史最早一行）——前端用于标注「数据仅从 X 起」
        cur.execute(
            "SELECT min(trade_date), max(trade_date) FROM bp_index_quote_daily"
            " WHERE symbol = %s AND adjust = 'bfq' AND close IS NOT NULL",
            (index_code,),
        )
        coverage_start, coverage_end = cur.fetchone()

        # overlay 价格窗口：MVI 区间起点（无 MVI 时用 range 起点），保证双轴对齐
        history = mvi.get("history") or []
        if history:
            price_start: Optional[date] = date.fromisoformat(history[0]["as_of"])
        elif coverage_end is not None and years is not None:
            price_start = _shift_years(coverage_end, -years)
        else:
            price_start = coverage_start

        series: list[dict] = []
        if price_start is not None:
            cur.execute(
                """
                SELECT trade_date, close FROM (
                    SELECT DISTINCT ON (trade_date) trade_date, close, updated_at
                    FROM bp_index_quote_daily
                    WHERE symbol = %s AND adjust = 'bfq' AND close IS NOT NULL
                      AND trade_date >= %s
                    ORDER BY trade_date, updated_at DESC,
                        CASE source
                            WHEN 'csindex_perf' THEN 0
                            WHEN 'cn_index_em' THEN 1
                            WHEN 'cn_index_sina' THEN 2
                            ELSE 9
                        END
                ) t
                ORDER BY trade_date
                """,
                (index_code, price_start),
            )
            series = [
                {"trade_date": trade_date, "close": _to_float(close)}
                for trade_date, close in cur.fetchall()
            ]

    return {
        "index_code": index_code,
        "name": name_row[0] if name_row else index_code,
        "series": series,
        "mvi": history,
        "range": range_key,
        "coverage_start": coverage_start,
        "coverage_end": coverage_end,
        "mvi_start": history[0]["as_of"] if history else None,
        "mvi_end": history[-1]["as_of"] if history else None,
        "missing": not series,
        "reason": None if series else "no_price_data_for_overlay",
    }


def get_index_price_series(
    conn: psycopg.Connection, index_code: str, years: int = 10
) -> list[dict]:
    """指数日线收盘（bfq，原币），近 N 年。用于详情页估值-点位双轴图。"""
    with conn.cursor() as cur:
        cur.execute(
            "SELECT max(trade_date) FROM bp_index_quote_daily"
            " WHERE symbol = %s AND adjust = 'bfq'",
            (index_code,),
        )
        row = cur.fetchone()
        last_date = row[0] if row else None
        if last_date is None:
            return []
        start = _shift_years(last_date, -max(1, int(years)))
        cur.execute(
            """
            SELECT trade_date, close FROM (
                SELECT DISTINCT ON (trade_date) trade_date, close, updated_at
                FROM bp_index_quote_daily
                WHERE symbol = %s AND adjust = 'bfq' AND close IS NOT NULL
                  AND trade_date >= %s
                ORDER BY trade_date, updated_at DESC,
                    CASE source
                        WHEN 'csindex_perf' THEN 0
                        WHEN 'cn_index_em' THEN 1
                        WHEN 'cn_index_sina' THEN 2
                        ELSE 9
                    END
            ) t
            ORDER BY trade_date
            """,
            (index_code, start),
        )
        return [
            {"trade_date": trade_date, "close": _to_float(close)}
            for trade_date, close in cur.fetchall()
        ]


def get_index_tracker_funds_meta(
    conn: psycopg.Connection, index_code: str
) -> dict:
    """跟踪基金数据截止/更新时间元信息（HSI 页右上角展示）。

    - data_as_of：bp_index_tracker_fund 最新 trade_date（基金规模/业绩数据截止日）；
    - updated_at：tracker 行最新 captured_at（本次入库/更新时间）；
    - risk_updated_at：bp_fund_risk 最新 updated_at（TE/波动等风险指标计算时间）；
    - fund_count：跟踪基金只数。
    """
    sql = """
        SELECT
            (SELECT max(trade_date) FROM bp_index_tracker_fund
              WHERE index_code = %(code)s) AS data_as_of,
            (SELECT max(captured_at) FROM bp_index_tracker_fund
              WHERE index_code = %(code)s) AS updated_at,
            (SELECT max(r.updated_at)
               FROM bp_index_tracker_fund t
               JOIN bp_fund_risk r USING (fund_code)
              WHERE t.index_code = %(code)s) AS risk_updated_at,
            (SELECT count(DISTINCT fund_code) FROM bp_index_tracker_fund
              WHERE index_code = %(code)s) AS fund_count
    """
    with conn.cursor() as cur:
        cur.execute(sql, {"code": index_code})
        record = cur.fetchone()
        columns = [desc.name for desc in cur.description]
    item = dict(zip(columns, record)) if record else {}
    item["fund_count"] = _to_int(item.get("fund_count")) or 0
    return item


def replace_market_valuation_index(
    conn: psycopg.Connection, rows: list[dict]
) -> int:
    """全量重算 MVI：先清空再写入（周频序列口径变更后避免残留旧点）。"""
    with conn.cursor() as cur:
        cur.execute("DELETE FROM bp_market_valuation_index")
    return upsert_market_valuation_index(conn, rows)


def upsert_macro_series(conn: psycopg.Connection, rows: list[dict]) -> int:
    """写入宏观序列（series_code + trade_date 幂等）。"""
    if not rows:
        return 0
    sql = """
        INSERT INTO bp_macro_series (series_code, trade_date, value, unit, source)
        VALUES (%(series_code)s, %(trade_date)s, %(value)s, %(unit)s, %(source)s)
        ON CONFLICT (series_code, trade_date) DO UPDATE SET
            value = EXCLUDED.value,
            unit = EXCLUDED.unit,
            source = EXCLUDED.source,
            captured_at = now()
    """
    with conn.cursor() as cur:
        cur.executemany(sql, rows)
    return len(rows)
