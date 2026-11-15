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
        )
        SELECT t.fund_code, COALESCE(f.name, t.fund_code) AS name,
               f.company_name, f.risk_grade, t.aum, t.trade_date,
               f.manager, f.fund_type, f.management_fee, f.custody_fee,
               f.established_date, f.fund_scale,
               p.ret_1m, p.ret_3m, p.ret_6m, p.ret_12m,
               p.ret_2y, p.ret_3y, p.ret_5y, p.ytd
        FROM bp_index_tracker_fund t
        LEFT JOIN bp_fund_master f USING (fund_code)
        LEFT JOIN LATERAL (
            SELECT * FROM bp_fund_performance perf
            WHERE perf.fund_code = t.fund_code
            ORDER BY perf.as_of DESC
            LIMIT 1
        ) p ON TRUE
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
        ):
            item[key] = _to_float(item.get(key))
        out.append(item)
    return out


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
