"""扩展只读行情端点：历史日线 / 汇率 / 基金净值。

- GET /api/v1/market/history  跨市场历史日线（A股/港股/ETF/指数，原币、可选复权）
- GET /api/v1/market/fx       汇率（人民币腿来自 fx_sina；交叉汇率按 A/CNY ÷ B/CNY 计算）
- GET /api/v1/fund/nav        场外基金净值（bp_fund_nav_daily）

全部为只读端点，统一信封 {data, meta, error}，scope 复用 quotes。
"""
from __future__ import annotations

import datetime as dt
import re
from typing import Any, Optional

from fastapi import Depends, FastAPI, Query, Request

from . import auth, db
from . import quote_store
from .public_api import (
    MAX_CODES,
    MAX_ROWS,
    ApiError,
    _api_error_handler,
    _build_auth_dependency,
    _csv_response,
    _envelope,
    _parse_adjust,
    _parse_codes,
    _parse_iso_date,
    _validate_limit,
    _validate_range,
    _wants_csv,
)

HISTORY_CSV_COLUMNS = (
    "code",
    "kind",
    "market",
    "currency",
    "date",
    "open",
    "high",
    "low",
    "close",
    "volume",
    "amount",
    "pct_change",
    "source",
    "adjust",
)
FX_CSV_COLUMNS = ("pair", "base", "quote", "date", "price", "source")
FUND_NAV_CSV_COLUMNS = ("code", "name", "date", "nav", "acc_nav", "source")

MAX_FX_PAIRS = 20
FX_SOURCE = "fx_sina"
_PAIR_RE = re.compile(r"^([A-Z]{3})([A-Z]{3})$")


# ---------------------------------------------------------------------
# 汇率
# ---------------------------------------------------------------------
def _parse_pairs(value: Optional[str]) -> list[tuple[str, str]]:
    if value is None or not value.strip():
        raise ApiError(400, "missing_parameter", "pairs 为必填参数")
    pairs: list[tuple[str, str]] = []
    seen: set[tuple[str, str]] = set()
    for item in value.split(","):
        text = item.strip().upper()
        if not text:
            continue
        compact = text.replace("/", "").replace("-", "").replace(".", "").replace("_", "")
        match = _PAIR_RE.match(compact)
        if not match:
            raise ApiError(
                400,
                "invalid_parameter",
                f"pair 格式非法: {item.strip()}（应形如 USD/CNY 或 USDCNY）",
                field="pairs",
                invalid=[item.strip()],
            )
        base, quote = match.groups()
        if base == quote:
            raise ApiError(400, "invalid_parameter", f"pair 两端币种相同: {item.strip()}", field="pairs")
        key = (base, quote)
        if key not in seen:
            seen.add(key)
            pairs.append(key)
    if not pairs:
        raise ApiError(400, "invalid_parameter", "pairs 不能为空")
    if len(pairs) > MAX_FX_PAIRS:
        raise ApiError(400, "too_many_pairs", f"pairs 最多 {MAX_FX_PAIRS} 个", max_pairs=MAX_FX_PAIRS)
    return pairs


def _legs(pairs: list[tuple[str, str]]) -> list[str]:
    legs: list[str] = []
    for base, quote in pairs:
        for currency in (base, quote):
            if currency != "CNY":
                leg = f"{currency}CNY"
                if leg not in legs:
                    legs.append(leg)
    return legs


def _fetch_fx(
    conn,
    pairs: list[tuple[str, str]],
    *,
    start: Optional[dt.date],
    end: Optional[dt.date],
    latest: bool,
) -> tuple[list[dict[str, Any]], list[str], Optional[str]]:
    legs = _legs(pairs)
    if not legs:
        return [], [], None
    scan_start = start
    if latest and scan_start is None:
        scan_start = dt.date.today() - dt.timedelta(days=30)
    with conn.cursor() as cur:
        cur.execute(
            "SELECT symbol, trade_date, close FROM bp_index_quote_daily"
            " WHERE symbol = ANY(%s) AND source = %s AND adjust = 'bfq'"
            " AND (%s::date IS NULL OR trade_date >= %s)"
            " AND (%s::date IS NULL OR trade_date <= %s)"
            " ORDER BY symbol, trade_date",
            (legs, FX_SOURCE, scan_start, scan_start, end, end),
        )
        fetched = cur.fetchall()
    by_leg: dict[str, dict[dt.date, Any]] = {leg: {} for leg in legs}
    for symbol, trade_date, close in fetched:
        if close is None:
            continue
        by_leg.setdefault(symbol, {})[trade_date] = float(close)
    missing = [leg for leg in legs if not by_leg.get(leg)]
    rows: list[dict[str, Any]] = []
    for base, quote in pairs:
        needed = [f"{c}CNY" for c in (base, quote) if c != "CNY"]
        if any(not by_leg.get(leg) for leg in needed):
            continue
        dates = None
        for leg in needed:
            leg_dates = set(by_leg[leg])
            dates = leg_dates if dates is None else (dates & leg_dates)
        if not dates:
            continue
        ordered = sorted(dates)
        if start is not None:
            ordered = [d for d in ordered if d >= start]
        if end is not None:
            ordered = [d for d in ordered if d <= end]
        if not ordered:
            continue
        selected = ordered[-1:] if latest else ordered
        for trade_date in selected:
            numerator = 1.0 if base == "CNY" else by_leg[f"{base}CNY"][trade_date]
            denominator = 1.0 if quote == "CNY" else by_leg[f"{quote}CNY"][trade_date]
            rows.append(
                {
                    "pair": f"{base}/{quote}",
                    "base": base,
                    "quote": quote,
                    "date": trade_date,
                    "price": numerator / denominator if denominator else None,
                    "source": FX_SOURCE,
                }
            )
    as_of = max((row["date"] for row in rows), default=None)
    return rows, missing, as_of.isoformat() if as_of else None


# ---------------------------------------------------------------------
# 基金净值
# ---------------------------------------------------------------------
def _fetch_fund_nav(
    conn,
    codes: list[str],
    *,
    start: Optional[dt.date],
    end: Optional[dt.date],
    latest: bool,
    limit: int,
) -> tuple[list[dict[str, Any]], list[str], bool]:
    with conn.cursor() as cur:
        cur.execute("SELECT fund_code, name FROM bp_fund_master WHERE fund_code = ANY(%s)", (codes,))
        names = {code: name for code, name in cur.fetchall()}
    rows: list[dict[str, Any]] = []
    truncated = False
    known = [code for code in codes if code in names]
    unknown = [code for code in codes if code not in names]
    if known:
        with conn.cursor() as cur:
            if latest:
                cur.execute(
                    "SELECT DISTINCT ON (fund_code) fund_code, trade_date, nav, acc_nav, source"
                    " FROM bp_fund_nav_daily WHERE fund_code = ANY(%s)"
                    " ORDER BY fund_code, trade_date DESC",
                    (known,),
                )
            else:
                cur.execute(
                    "SELECT fund_code, trade_date, nav, acc_nav, source FROM bp_fund_nav_daily"
                    " WHERE fund_code = ANY(%s)"
                    " AND (%s::date IS NULL OR trade_date >= %s)"
                    " AND (%s::date IS NULL OR trade_date <= %s)"
                    " ORDER BY fund_code, trade_date LIMIT %s",
                    (known, start, start, end, end, limit + 1),
                )
            fetched = cur.fetchall()
        if len(fetched) > limit:
            truncated = True
            fetched = fetched[:limit]
        for code, trade_date, nav, acc_nav, source in fetched:
            rows.append(
                {
                    "code": code,
                    "name": names.get(code, ""),
                    "date": trade_date,
                    "nav": nav,
                    "acc_nav": acc_nav,
                    "source": source,
                }
            )
    rows.sort(key=lambda row: (row["code"], row["date"]))
    return rows, unknown, truncated


def register_routes(app: FastAPI) -> None:
    """注册扩展 /api/v1 端点（由 main.py 调用）。"""
    app.add_exception_handler(ApiError, _api_error_handler)
    quotes_dep = _build_auth_dependency("quotes")

    # ---- 历史日线 ----------------------------------------------------
    @app.get("/api/v1/market/history", tags=["public-api"])
    def market_history(
        request: Request,
        codes: Optional[str] = Query(None, description="逗号分隔代码，最多 50 个"),
        start: Optional[str] = Query(None, description="ISO 日期 YYYY-MM-DD"),
        end: Optional[str] = Query(None, description="ISO 日期 YYYY-MM-DD"),
        adjust: str = Query("bfq", description="复权口径 bfq/hfq（qfq 已停用）"),
        limit: int = Query(MAX_ROWS, description="最大返回行数，上限 50000"),
        output_format: Optional[str] = Query(None, alias="format", description="json 或 csv"),
        _token: Any = Depends(quotes_dep),
    ):
        code_list = _parse_codes(codes)
        start_date = _parse_iso_date(start, "start")
        end_date = _parse_iso_date(end, "end")
        _validate_range(start_date, end_date)
        adjust_value = _parse_adjust(adjust)
        row_limit = _validate_limit(limit)
        as_csv = _wants_csv(request, output_format)
        with db.get_conn() as conn:
            resolved, invalid = quote_store.resolve_codes(conn, code_list, adjust_value)
            rows, truncated = quote_store.history_rows(
                conn,
                resolved,
                adjust=adjust_value,
                start=start_date,
                end=end_date,
                limit=row_limit,
            )
        if as_csv:
            return _csv_response(rows, HISTORY_CSV_COLUMNS, "market_history.csv")
        return _envelope(
            rows,
            rows=len(rows),
            requested=len(code_list),
            invalid=invalid,
            adjust=adjust_value,
            limit=row_limit,
            truncated=truncated,
            source="bp_stock_quote_daily | bp_etf_quote_daily | bp_index_quote_daily",
        )

    # ---- 汇率 --------------------------------------------------------
    @app.get("/api/v1/market/fx", tags=["public-api"])
    def market_fx(
        request: Request,
        pairs: Optional[str] = Query(None, description="逗号分隔货币对，如 USD/CNY,HKD/CNY,USD/HKD,USD/SGD"),
        start: Optional[str] = Query(None, description="ISO 日期（省略则返回最新快照）"),
        end: Optional[str] = Query(None, description="ISO 日期"),
        output_format: Optional[str] = Query(None, alias="format", description="json 或 csv"),
        _token: Any = Depends(quotes_dep),
    ):
        pair_list = _parse_pairs(pairs)
        start_date = _parse_iso_date(start, "start")
        end_date = _parse_iso_date(end, "end")
        _validate_range(start_date, end_date)
        latest = start_date is None and end_date is None
        as_csv = _wants_csv(request, output_format)
        with db.get_conn() as conn:
            rows, missing, as_of = _fetch_fx(
                conn, pair_list, start=start_date, end=end_date, latest=latest
            )
        if as_csv:
            return _csv_response(rows, FX_CSV_COLUMNS, "market_fx.csv")
        return _envelope(
            rows,
            rows=len(rows),
            pairs=[f"{base}/{quote}" for base, quote in pair_list],
            mode="latest" if latest else "history",
            missing_legs=missing,
            as_of=as_of,
            source=FX_SOURCE,
            note="交叉汇率按 A/CNY ÷ B/CNY 由同一日人民币腿计算",
        )

    # ---- 基金净值 ----------------------------------------------------
    @app.get("/api/v1/fund/nav", tags=["public-api"])
    def fund_nav(
        request: Request,
        codes: Optional[str] = Query(None, description="逗号分隔基金代码，最多 50 个"),
        start: Optional[str] = Query(None, description="ISO 日期 YYYY-MM-DD"),
        end: Optional[str] = Query(None, description="ISO 日期 YYYY-MM-DD"),
        latest: bool = Query(False, description="true 时每个基金只返回最新一条净值"),
        limit: int = Query(MAX_ROWS, description="最大返回行数，上限 50000"),
        output_format: Optional[str] = Query(None, alias="format", description="json 或 csv"),
        _token: Any = Depends(quotes_dep),
    ):
        code_list = _parse_codes(codes)
        start_date = _parse_iso_date(start, "start")
        end_date = _parse_iso_date(end, "end")
        _validate_range(start_date, end_date)
        row_limit = _validate_limit(limit)
        as_csv = _wants_csv(request, output_format)
        with db.get_conn() as conn:
            rows, unknown, truncated = _fetch_fund_nav(
                conn,
                code_list,
                start=start_date,
                end=end_date,
                latest=latest,
                limit=row_limit,
            )
        if as_csv:
            return _csv_response(rows, FUND_NAV_CSV_COLUMNS, "fund_nav.csv")
        return _envelope(
            rows,
            rows=len(rows),
            requested=len(code_list),
            unknown=unknown,
            mode="latest" if latest else "history",
            limit=row_limit,
            truncated=truncated,
            source="bp_fund_nav_daily",
        )
