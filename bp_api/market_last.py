"""最新行情快照 API（GET /api/v1/market/last）——只读「已落库确认的收盘价」。

面向 Excel / BI：一次请求返回一组代码的最新一条日线。

口径契约（与项目回测/清洗口径保持一致，Excel 侧不得引入盘中实时价）：

- 默认只读数据库日线（bp_stock_quote_daily / bp_etf_quote_daily /
  bp_index_quote_daily），**不做实时行情兜底**；
- 现价口径 = 不复权 bfq，原币计价（港股返回 HKD，A 股/ETF/指数返回 CNY）；
- 返回每行 date（数据日期）+ status（ok / unknown），Excel 侧据此显示数据日期；
- 代码规范：601318.SH / 002352.SZ / 02020.HK / 159915.SZ；也接受裸代码、
  sh601318、hk02020；指数可用 IDX:000300 强制解析。
"""
from __future__ import annotations

import datetime as dt
from typing import Any, Optional

from fastapi import Depends, FastAPI, Query, Request

from . import auth, db
from . import quote_store
from .public_api import (
    MAX_CODES,
    ApiError,
    _api_error_handler,
    _build_auth_dependency,
    _csv_response,
    _envelope,
    _parse_adjust,
    _parse_codes,
    _wants_csv,
)

CSV_COLUMNS = (
    "code",
    "market",
    "currency",
    "kind",
    "name",
    "date",
    "close",
    "prev_close",
    "pct",
    "adjust",
    "source",
    "status",
)


def _fetch_latest(
    conn, code_list: list[str], adjust: str
) -> tuple[list[dict[str, Any]], list[str], list[str], Optional[str]]:
    """返回 (rows, invalid, unknown, as_of)。"""
    resolved, invalid = quote_store.resolve_codes(conn, code_list, adjust)
    latest = quote_store.latest_rows(conn, resolved, adjust)
    rows: list[dict[str, Any]] = []
    unknown: list[str] = []
    as_of: Optional[dt.date] = None
    for raw in code_list:
        info = resolved.get(raw)
        if info is None:
            continue
        data = latest.get(raw)
        if data is None:
            unknown.append(info["canonical"])
            rows.append(
                {
                    "code": info["canonical"],
                    "market": info["market"],
                    "currency": info["currency"],
                    "kind": info["kind"],
                    "name": info["name"],
                    "date": None,
                    "close": None,
                    "prev_close": None,
                    "pct": None,
                    "adjust": adjust,
                    "source": None,
                    "status": "unknown",
                }
            )
            continue
        trade_date = data["date"]
        if isinstance(trade_date, dt.date) and (as_of is None or trade_date > as_of):
            as_of = trade_date
        close = data["close"]
        prev_close = data.get("prev_close")
        pct = None
        if close is not None and prev_close:
            pct = (float(close) / float(prev_close) - 1.0) * 100.0
        rows.append(
            {
                "code": info["canonical"],
                "market": info["market"],
                "currency": info["currency"],
                "kind": info["kind"],
                "name": info["name"],
                "date": trade_date,
                "close": close,
                "prev_close": prev_close,
                "pct": pct,
                "adjust": data.get("adjust", adjust),
                "source": data.get("source"),
                "status": "ok",
            }
        )
    return rows, invalid, unknown, as_of.isoformat() if as_of else None


def register_routes(app: FastAPI) -> None:
    """注册 /api/v1/market/last（由 main.py 调用）。"""
    app.add_exception_handler(ApiError, _api_error_handler)
    quotes_dep = _build_auth_dependency("quotes")

    @app.get("/api/v1/market/last", tags=["public-api"])
    def market_last(
        request: Request,
        codes: Optional[str] = Query(None, description="逗号分隔代码，最多 50 个；支持 601318.SH / 02020.HK"),
        adjust: str = Query("bfq", description="复权口径 bfq/hfq（现价用 bfq；qfq 已停用）"),
        output_format: Optional[str] = Query(None, alias="format", description="json 或 csv"),
        _token: Any = Depends(quotes_dep),
    ):
        code_list = _parse_codes(codes, max_codes=MAX_CODES)
        adjust_value = _parse_adjust(adjust)
        as_csv = _wants_csv(request, output_format)
        with db.get_conn() as conn:
            rows, invalid, unknown, as_of = _fetch_latest(conn, code_list, adjust_value)
            latest_trade_date = quote_store.latest_trade_date(conn)
        if as_csv:
            return _csv_response(rows, CSV_COLUMNS, "market_last.csv")
        return _envelope(
            rows,
            rows=len(rows),
            requested=len(code_list),
            codes=[row["code"] for row in rows],
            as_of=as_of,
            latest_trade_date=latest_trade_date.isoformat() if latest_trade_date else None,
            adjust=adjust_value,
            invalid=invalid,
            unknown=unknown,
            source="bp_stock_quote_daily | bp_etf_quote_daily | bp_index_quote_daily",
            price_basis="last_confirmed_close",
        )
