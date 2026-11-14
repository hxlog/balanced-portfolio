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
PERCENTILE_WINDOWS = frozenset({"5y", "10y", "all"})
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


def get_index_list(
    conn: psycopg.Connection,
    *,
    query: Optional[str],
    index_type: Optional[str],
    only_with_etf: bool,
    only_with_valuation: bool,
    limit: int,
    offset: int,
) -> tuple[list[dict], int]:
    """指数列表（单条 SQL）。

    一条 CTE + 三个 LATERAL 完成「主数据 + 最新主口径估值 + 最新 PE/PB 分位」，
    并用锚点行保证空页也能拿到 total，绝不产生 N+1。
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
                m.market,
                m.publisher,
                v.trade_date,
                v.calc_src,
                v.pe_ttm,
                v.pb,
                v.dividend_yield_ttm,
                v.erp,
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
                q1.close AS close_price,
                CASE
                    WHEN q1.close > 0 AND q2.close > 0
                    THEN ((q1.close / q2.close) - 1) * 100
                END AS change_pct,
                pe.pct AS pe_percentile,
                pe.as_of_date AS pe_pct_as_of,
                pb.pct AS pb_percentile,
                pb.as_of_date AS pb_pct_as_of
            FROM bp_index_master m
            LEFT JOIN LATERAL (
                SELECT
                    d.index_code, d.trade_date, d.calc_src, d.pe_ttm, d.pb,
                    d.dividend_yield_ttm, d.erp, d.level_pe, d.level_pb,
                    d.level_dividend, d.captured_at, d.raw
                FROM bp_index_valuation_daily d
                WHERE d.index_code = m.index_code AND d.is_primary
                ORDER BY d.trade_date DESC
                LIMIT 1
            ) v ON TRUE
            LEFT JOIN LATERAL (
                SELECT p.pct, p.as_of_date
                FROM bp_index_percentile p
                WHERE p.index_code = m.index_code
                  AND p.metric = 'pe_ttm'
                  AND p.window_key = '5y'
                  AND p.calc_src = v.calc_src
                ORDER BY p.as_of_date DESC
                LIMIT 1
            ) pe ON TRUE
            LEFT JOIN LATERAL (
                SELECT p.pct, p.as_of_date
                FROM bp_index_percentile p
                WHERE p.index_code = m.index_code
                  AND p.metric = 'pb'
                  AND p.window_key = '5y'
                  AND p.calc_src = v.calc_src
                ORDER BY p.as_of_date DESC
                LIMIT 1
            ) pb ON TRUE
            LEFT JOIN LATERAL (
                SELECT q.close, q.trade_date
                FROM bp_quote_clean q
                WHERE q.symbol = m.index_code AND q.adjust = 'bfq'
                ORDER BY q.trade_date DESC
                LIMIT 1
            ) q1 ON TRUE
            LEFT JOIN LATERAL (
                SELECT q.close
                FROM bp_quote_clean q
                WHERE q.symbol = m.index_code AND q.adjust = 'bfq'
                  AND q1.trade_date IS NOT NULL
                  AND q.trade_date < q1.trade_date
                ORDER BY q.trade_date DESC
                LIMIT 1
            ) q2 ON TRUE
            WHERE (%(query)s::text IS NULL
                   OR m.index_code ILIKE %(query_like)s
                   OR m.name ILIKE %(query_like)s
                   OR COALESCE(m.short_name, '') ILIKE %(query_like)s)
              AND (%(index_type)s::text IS NULL
                   OR m.index_type = %(index_type)s::text)
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
        "close_price",
        "change_pct",
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
            m.income_method, m.weight_method, m.intro, m.is_active, m.is_tracked,
            d.trade_date, d.calc_src, d.pe_ttm, d.pe_static, d.pb,
            d.dividend_yield_ttm, d.dividend_yield_lyr, d.roe_ttm, d.roa_ttm,
            d.bond10y, d.erp, d.pe_basis, d.pb_basis, d.div_basis,
            d.level_pe, d.level_pb, d.level_dividend, d.is_primary,
            d.captured_at, d.raw
        FROM bp_index_master m
        LEFT JOIN LATERAL (
            SELECT *
            FROM bp_index_valuation_daily dd
            WHERE dd.index_code = m.index_code AND dd.is_primary
            ORDER BY dd.trade_date DESC
            LIMIT 1
        ) d ON TRUE
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
    if window == "5y":
        start = _shift_years(end, -5)
    elif window == "10y":
        start = _shift_years(end, -10)

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
