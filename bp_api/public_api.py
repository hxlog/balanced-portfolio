"""对外数据 API —— ``/api/v1`` 只读端点。

设计约束（见 ``docs/index-valuation/06-data-model-v3.md`` §2.8 与
``docs/API.md``）：

- 请求路径**永不计算**：行情读 ``bp_quote_clean``，估值读
  ``bp_index_valuation_daily(is_primary)``，分位读预计算表
  ``bp_index_percentile``，宏观利率读 ``bp_macro_series``；
- 全部端点统一信封 ``{"data", "meta", "error"}``；
- 鉴权统一走 ``auth.require_api_token``。该依赖由 P2-A 并行交付，既可能是
  ``require_api_token(scope) -> dependency`` 工厂，也可能是直接依赖函数，
  本模块在注册时自动识别；模块尚未合入时降级为恒 401 的占位依赖，保证
  本模块可独立导入（``main.py`` 的路由注册冒烟测试不被拖垮）；
- JSON 实参统一经 ``repositories._json_safe`` 清洗（NaN/Inf -> None）；
- 支持 ``?format=csv`` 或 ``Accept: text/csv``，CSV 带 UTF-8 BOM。
"""

from __future__ import annotations

import csv
import datetime as dt
import inspect
import io
import json
import re
from datetime import date, datetime
from decimal import Decimal
from functools import wraps
from typing import Any, Callable, Iterator, Optional, Sequence

import psycopg
from fastapi import Depends, FastAPI, Header, HTTPException, Query, Request
from fastapi.exception_handlers import request_validation_exception_handler
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse, StreamingResponse

from . import auth, db
from . import repositories_valuation
from .repositories import _json_safe

# ---------------------------------------------------------------------------
# 常量
# ---------------------------------------------------------------------------
MAX_CODES = 50
MAX_ROWS = 50_000
ADJUST_MODES = frozenset({"bfq", "hfq"})  # qfq 已于 2026-11 停用（76 号迁移）
DEFAULT_VALUATION_FIELDS = ("pe_ttm", "pb", "dividend_yield_ttm", "erp")
VALUATION_FIELDS = frozenset(DEFAULT_VALUATION_FIELDS)
# bp_index_valuation_series.ck_series_metric / bp_index_percentile.metric
PERCENTILE_METRICS = frozenset(
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
BOND_SERIES_CODE = "cn_10y_yield"

MARKET_DAILY_CSV_COLUMNS = (
    "code",
    "source",
    "date",
    "open",
    "high",
    "low",
    "close",
    "ret",
)
BOND_YIELD_CSV_COLUMNS = ("date", "value", "unit", "source")
PERCENTILE_CSV_COLUMNS = (
    "code",
    "as_of",
    "metric",
    "window",
    "calc_src",
    "pct",
    "mean",
    "sd",
    "p20",
    "p50",
    "p80",
    "min_value",
    "max_value",
    "sample_size",
)

_DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")


# ---------------------------------------------------------------------------
# 错误与信封
# ---------------------------------------------------------------------------
class ApiError(Exception):
    """对外 API 的统一业务异常（由异常处理器渲染为信封）。"""

    def __init__(
        self,
        status_code: int,
        code: str,
        message: str,
        **meta: Any,
    ) -> None:
        super().__init__(message)
        self.status_code = status_code
        self.code = code
        self.message = message
        self.meta = meta
        # 401 需携 WWW-Authenticate、429 需携 Retry-After，转换时必须原样透传。
        self.headers: Optional[dict[str, str]] = None


def _http_to_api_error(exc: HTTPException, *, scope: Optional[str] = None) -> ApiError:
    """把 FastAPI 依赖抛出的 ``HTTPException`` 转成信封错误。"""
    status = int(exc.status_code)
    code = {
        400: "invalid_parameter",
        401: "unauthorized",
        403: "forbidden",
        404: "not_found",
        422: "validation_error",
    }.get(status, "error")
    detail = exc.detail
    meta: dict[str, Any] = {}
    if isinstance(detail, dict):
        code = str(detail.get("code") or code)
        message = str(detail.get("message") or detail.get("detail") or detail)
        meta = {
            key: value
            for key, value in detail.items()
            if key not in ("code", "message", "detail")
        }
    else:
        message = str(detail)
    if status == 403 and scope:
        meta.setdefault("required_scope", scope)
    error = ApiError(status, code, message, **meta)
    error.headers = dict(exc.headers or {})
    return error


def _api_safe(obj: Any) -> Any:
    """date/Decimal -> JSON 原生类型，再走 ``_json_safe`` 清 NaN/Inf。"""
    if isinstance(obj, dict):
        return {str(key): _api_safe(value) for key, value in obj.items()}
    if isinstance(obj, (list, tuple)):
        return [_api_safe(value) for value in obj]
    if isinstance(obj, (datetime, date)):
        return obj.isoformat()
    if isinstance(obj, Decimal):
        return _json_safe(float(obj))
    return _json_safe(obj)


def _latest_as_of(data: Any) -> Optional[str]:
    rows = data if isinstance(data, list) else [data]
    candidates: list[str] = []
    for row in rows:
        if not isinstance(row, dict):
            continue
        for key in ("date", "as_of", "trade_date"):
            value = row.get(key)
            if value is None:
                continue
            if isinstance(value, (datetime, date)):
                value = value.isoformat()
            candidates.append(str(value))
            break
    return max(candidates) if candidates else None


def _envelope(data: Any, *, rows: Optional[int] = None, **meta: Any) -> dict:
    meta_out: dict[str, Any] = {"cached": False}
    if rows is not None:
        meta_out["rows"] = rows
    as_of = _latest_as_of(data)
    if as_of is not None:
        meta_out["as_of"] = as_of
    meta_out.update(meta)
    return {
        "data": _api_safe(data),
        "meta": _api_safe(meta_out),
        "error": None,
    }


async def _api_error_handler(_request: Request, exc: ApiError) -> JSONResponse:
    meta = _api_safe(exc.meta)
    return JSONResponse(
        status_code=exc.status_code,
        headers=getattr(exc, "headers", None) or None,
        content={
            "data": None,
            "meta": meta,
            "error": {"code": exc.code, "message": exc.message, **meta},
        },
    )


async def _request_validation_handler(
    request: Request, exc: RequestValidationError
) -> Any:
    """``/api/v1`` 的参数解析失败也走统一信封；其他路由保持 FastAPI 默认行为。"""
    if not request.url.path.startswith("/api/v1/"):
        return await request_validation_exception_handler(request, exc)

    details = [
        {
            "loc": [str(part) for part in error.get("loc", ())],
            "msg": str(error.get("msg", "")),
            "type": str(error.get("type", "")),
        }
        for error in exc.errors()
    ]
    return JSONResponse(
        status_code=422,
        content={
            "data": None,
            "meta": {"details": details},
            "error": {
                "code": "validation_error",
                "message": "参数校验失败",
                "details": details,
            },
        },
    )


# ---------------------------------------------------------------------------
# 鉴权依赖（兼容工厂 / 直接依赖两种 P2-A 形态）
# ---------------------------------------------------------------------------
def _param_names(fn: Callable[..., Any]) -> set[str]:
    try:
        return set(inspect.signature(fn).parameters)
    except (TypeError, ValueError):
        return set()


def _extract_scopes(token: Any) -> Optional[set[str]]:
    scopes = getattr(token, "scopes", None)
    if scopes is None and isinstance(token, dict):
        scopes = token.get("scopes")
    if scopes is None:
        return None
    if isinstance(scopes, str):
        return {item.strip() for item in scopes.split(",") if item.strip()}
    try:
        return {str(item) for item in scopes}
    except TypeError:
        return None


def _enforce_scope(token: Any, scope: Optional[str]) -> None:
    if scope is None:
        return
    scopes = _extract_scopes(token)
    if scopes is not None and scope not in scopes:
        raise ApiError(
            403,
            "forbidden",
            f"该 Token 缺少 {scope} 权限",
            required_scope=scope,
            scopes=sorted(scopes),
        )


def _wrap_dependency(fn: Callable[..., Any], scope: Optional[str]) -> Callable[..., Any]:
    """包一层：HTTPException -> ApiError，并补一次 scope 校验。"""

    if inspect.iscoroutinefunction(fn):

        @wraps(fn)
        async def async_dependency(*args: Any, **kwargs: Any) -> Any:
            try:
                token = await fn(*args, **kwargs)
            except ApiError:
                raise
            except HTTPException as exc:
                raise _http_to_api_error(exc, scope=scope) from exc
            _enforce_scope(token, scope)
            return token

        return async_dependency

    @wraps(fn)
    def sync_dependency(*args: Any, **kwargs: Any) -> Any:
        try:
            token = fn(*args, **kwargs)
        except ApiError:
            raise
        except HTTPException as exc:
            raise _http_to_api_error(exc, scope=scope) from exc
        _enforce_scope(token, scope)
        return token

    return sync_dependency


def _build_auth_dependency(scope: str) -> Callable[..., Any]:
    provider = getattr(auth, "require_api_token", None)
    if provider is None:

        def _missing_token(
            authorization: str = Header(default=""),
            x_api_key: str = Header(default=""),
        ) -> Any:
            raise ApiError(401, "unauthorized", "缺少或无效的 API Token")

        return _missing_token

    names = _param_names(provider)
    if "authorization" in names or "x_api_key" in names:
        # 直接依赖形态：Depends(require_api_token)
        return _wrap_dependency(provider, scope)

    # 工厂形态：require_api_token(scope) -> dependency
    try:
        dependency = provider(scope)
    except TypeError:
        dependency = provider()
    if not callable(dependency):
        return _wrap_dependency(provider, scope)
    return _wrap_dependency(dependency, scope)


# ---------------------------------------------------------------------------
# 参数校验
# ---------------------------------------------------------------------------
def _parse_codes(codes: Optional[str], *, max_codes: int = MAX_CODES) -> list[str]:
    if codes is None or not codes.strip():
        raise ApiError(400, "missing_parameter", "codes 为必填参数")
    items = [item.strip() for item in codes.split(",") if item.strip()]
    if not items:
        raise ApiError(400, "invalid_parameter", "codes 不能为空")
    unique = list(dict.fromkeys(items))
    if len(unique) > max_codes:
        raise ApiError(
            400,
            "too_many_codes",
            f"codes 最多 {max_codes} 个",
            max_codes=max_codes,
            count=len(unique),
        )
    return unique


def _parse_iso_date(value: Optional[str], field: str) -> Optional[date]:
    if value is None or not value.strip():
        return None
    text = value.strip()
    if not _DATE_RE.fullmatch(text):
        raise ApiError(
            422,
            "invalid_date",
            f"{field} 必须为 ISO 日期 YYYY-MM-DD",
            field=field,
        )
    try:
        return dt.date.fromisoformat(text)
    except ValueError as exc:
        raise ApiError(
            422,
            "invalid_date",
            f"{field} 不是合法日期",
            field=field,
        ) from exc


def _validate_range(start: Optional[date], end: Optional[date]) -> None:
    if start is not None and end is not None and start > end:
        raise ApiError(
            422,
            "invalid_range",
            "start 不能晚于 end",
            start=start.isoformat(),
            end=end.isoformat(),
        )


def _validate_limit(limit: int) -> int:
    if limit < 1 or limit > MAX_ROWS:
        raise ApiError(
            422,
            "invalid_limit",
            f"limit 必须在 1..{MAX_ROWS} 之间",
            max_limit=MAX_ROWS,
        )
    return int(limit)


def _parse_list_param(
    value: Optional[str],
    *,
    default: Sequence[str],
    allowed: frozenset[str],
    field: str,
) -> list[str]:
    if value is None or not value.strip():
        items = list(default)
    else:
        items = [item.strip() for item in value.split(",") if item.strip()]
    if not items:
        raise ApiError(400, "invalid_parameter", f"{field} 不能为空", field=field)
    invalid = [item for item in items if item not in allowed]
    if invalid:
        raise ApiError(
            400,
            "invalid_parameter",
            f"{field} 含非法值: {', '.join(invalid)}",
            field=field,
            invalid=invalid,
            allowed=sorted(allowed),
        )
    return list(dict.fromkeys(items))


def _parse_adjust(value: str) -> str:
    adjust = (value or "").strip().lower()
    if adjust == "qfq":
        raise ApiError(
            400,
            "invalid_parameter",
            "qfq（前复权）已停用；仅支持 bfq / hfq",
            field="adjust",
            allowed=sorted(ADJUST_MODES),
            retired=["qfq"],
        )
    if adjust not in ADJUST_MODES:
        raise ApiError(
            400,
            "invalid_parameter",
            "adjust 仅支持 bfq / hfq（qfq 已停用）",
            field="adjust",
            allowed=sorted(ADJUST_MODES),
        )
    return adjust


def _wants_csv(request: Request, output_format: Optional[str]) -> bool:
    if output_format is not None and output_format.strip():
        choice = output_format.strip().lower()
        if choice not in ("json", "csv"):
            raise ApiError(
                400,
                "invalid_parameter",
                "format 仅支持 json / csv",
                field="format",
                allowed=["json", "csv"],
            )
        return choice == "csv"
    return "text/csv" in request.headers.get("accept", "").lower()


# ---------------------------------------------------------------------------
# CSV
# ---------------------------------------------------------------------------
def _csv_value(value: Any) -> Any:
    if value is None:
        return ""
    if isinstance(value, (dict, list, tuple)):
        return json.dumps(_api_safe(value), ensure_ascii=False)
    return value


def _csv_chunks(rows: Sequence[dict], columns: Sequence[str]) -> Iterator[bytes]:
    buffer = io.StringIO()
    writer = csv.DictWriter(buffer, fieldnames=list(columns), extrasaction="ignore")
    writer.writeheader()
    # UTF-8 BOM: Excel 双击打开时按 UTF-8 解码，避免中文乱码。
    yield (chr(0xFEFF) + buffer.getvalue()).encode("utf-8")
    for row in rows:
        buffer.seek(0)
        buffer.truncate(0)
        writer.writerow({column: _csv_value(row.get(column)) for column in columns})
        yield buffer.getvalue().encode("utf-8")


def _csv_response(
    rows: Sequence[dict], columns: Sequence[str], filename: str
) -> StreamingResponse:
    safe_rows = _api_safe(list(rows))
    return StreamingResponse(
        _csv_chunks(safe_rows, columns),
        media_type="text/csv; charset=utf-8",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


# ---------------------------------------------------------------------------
# 数据读取（只读；请求路径绝不重算）
# ---------------------------------------------------------------------------
def _fetch_market_daily(
    conn: psycopg.Connection,
    *,
    codes: list[str],
    adjust: str,
    start: Optional[date],
    end: Optional[date],
    limit: int,
) -> tuple[list[dict], list[str], bool]:
    params: dict[str, Any] = {
        "codes": codes,
        "adjust": adjust,
        "limit": limit + 1,
    }
    conditions = ["symbol = ANY(%(codes)s)", "adjust = %(adjust)s"]
    if start is not None:
        conditions.append("trade_date >= %(start)s")
        params["start"] = start
    if end is not None:
        conditions.append("trade_date <= %(end)s")
        params["end"] = end

    # 同一 (symbol, trade_date) 可能有多源（东财/新浪/腾讯）重复行。对外 API 必须去重，
    # 否则 Excel 侧会双计。优先级：非备份源优先（bp_data_source.is_backup），再按源码排序。
    data_conditions = ["q.symbol = ANY(%(codes)s)", "q.adjust = %(adjust)s"]
    if start is not None:
        data_conditions.append("q.trade_date >= %(start)s")
    if end is not None:
        data_conditions.append("q.trade_date <= %(end)s")

    data_sql = (
        "SELECT symbol, source, trade_date, open, high, low, close, ret FROM ("
        "  SELECT DISTINCT ON (q.symbol, q.trade_date)"
        "         q.symbol, q.source, q.trade_date, q.open, q.high, q.low, q.close, q.ret"
        "  FROM bp_quote_clean q"
        "  LEFT JOIN bp_data_source d ON d.code = q.source"
        "  WHERE " + " AND ".join(data_conditions) +
        "  ORDER BY q.symbol, q.trade_date, COALESCE(d.is_backup, FALSE) ASC, q.source"
        ") dedup ORDER BY trade_date, symbol LIMIT %(limit)s"
    )
    known_sql = (
        "SELECT DISTINCT symbol FROM bp_quote_clean "
        "WHERE symbol = ANY(%(codes)s) AND adjust = %(adjust)s"
    )

    with conn.cursor() as cur:
        cur.execute(known_sql, {"codes": codes, "adjust": adjust})
        known = {row[0] for row in cur.fetchall()}
        cur.execute(data_sql, params)
        records = cur.fetchall()

    unknown = [code for code in codes if code not in known]
    truncated = len(records) > limit
    rows = [
        {
            "code": symbol,
            "source": source,
            "date": trade_date,
            "open": open_,
            "high": high,
            "low": low,
            "close": close,
            "ret": ret,
        }
        for symbol, source, trade_date, open_, high, low, close, ret in records[:limit]
    ]
    return rows, unknown, truncated


def _fetch_index_valuation(
    conn: psycopg.Connection,
    *,
    codes: list[str],
    fields: list[str],
    start: Optional[date],
    end: Optional[date],
    limit: int,
) -> tuple[list[dict], list[str], bool]:
    params: dict[str, Any] = {
        "codes": codes,
        "limit": limit + 1,
    }
    conditions = ["is_primary", "index_code = ANY(%(codes)s)"]
    if start is not None:
        conditions.append("trade_date >= %(start)s")
        params["start"] = start
    if end is not None:
        conditions.append("trade_date <= %(end)s")
        params["end"] = end

    columns = ", ".join(fields)
    data_sql = (
        f"SELECT index_code, trade_date, {columns} "
        "FROM bp_index_valuation_daily WHERE "
        + " AND ".join(conditions)
        + " ORDER BY trade_date, index_code LIMIT %(limit)s"
    )
    known_sql = "SELECT index_code FROM bp_index_master WHERE index_code = ANY(%(codes)s)"

    with conn.cursor() as cur:
        cur.execute(known_sql, {"codes": codes})
        known = {row[0] for row in cur.fetchall()}
        cur.execute(data_sql, params)
        records = cur.fetchall()

    unknown = [code for code in codes if code not in known]
    truncated = len(records) > limit
    rows: list[dict] = []
    for record in records[:limit]:
        row = {"code": record[0], "date": record[1]}
        for name, value in zip(fields, record[2:]):
            row[name] = value
        rows.append(row)
    return rows, unknown, truncated


def _fetch_index_percentile(
    conn: psycopg.Connection,
    *,
    codes: list[str],
    metrics: list[str],
    windows: list[str],
    limit: int,
) -> tuple[list[dict], list[str], bool]:
    sql = """
        SELECT DISTINCT ON (index_code, metric, window_key)
               index_code, as_of_date, metric, window_key, calc_src,
               pct, mean, sd, p20, p50, p80, min_value, max_value, sample_size
        FROM bp_index_percentile
        WHERE index_code = ANY(%(codes)s)
          AND metric = ANY(%(metrics)s)
          AND window_key = ANY(%(windows)s)
        ORDER BY index_code, metric, window_key, as_of_date DESC, calc_src
        LIMIT %(limit)s
    """
    known_sql = "SELECT index_code FROM bp_index_master WHERE index_code = ANY(%(codes)s)"
    params = {
        "codes": codes,
        "metrics": metrics,
        "windows": windows,
        "limit": limit + 1,
    }

    with conn.cursor() as cur:
        cur.execute(known_sql, {"codes": codes})
        known = {row[0] for row in cur.fetchall()}
        cur.execute(sql, params)
        records = cur.fetchall()

    unknown = [code for code in codes if code not in known]
    truncated = len(records) > limit
    rows = [
        {
            "code": index_code,
            "as_of": as_of_date,
            "metric": metric,
            "window": window_key,
            "calc_src": calc_src,
            "pct": pct,
            "mean": mean,
            "sd": sd,
            "p20": p20,
            "p50": p50,
            "p80": p80,
            "min_value": min_value,
            "max_value": max_value,
            "sample_size": sample_size,
        }
        for (
            index_code,
            as_of_date,
            metric,
            window_key,
            calc_src,
            pct,
            mean,
            sd,
            p20,
            p50,
            p80,
            min_value,
            max_value,
            sample_size,
        ) in records[:limit]
    ]
    return rows, unknown, truncated


def _fetch_bond_yield(
    conn: psycopg.Connection,
    *,
    start: Optional[date],
    end: Optional[date],
    limit: int,
) -> tuple[list[dict], bool]:
    params: dict[str, Any] = {
        "series_code": BOND_SERIES_CODE,
        "limit": limit + 1,
    }
    conditions = ["series_code = %(series_code)s"]
    if start is not None:
        conditions.append("trade_date >= %(start)s")
        params["start"] = start
    if end is not None:
        conditions.append("trade_date <= %(end)s")
        params["end"] = end

    sql = (
        "SELECT trade_date, value, unit, source FROM bp_macro_series WHERE "
        + " AND ".join(conditions)
        + " ORDER BY trade_date LIMIT %(limit)s"
    )
    with conn.cursor() as cur:
        cur.execute(sql, params)
        records = cur.fetchall()

    truncated = len(records) > limit
    rows = [
        {"date": trade_date, "value": value, "unit": unit, "source": source}
        for trade_date, value, unit, source in records[:limit]
    ]
    return rows, truncated


def _load_index_detail(conn: psycopg.Connection, code: str) -> Optional[dict]:
    detail = repositories_valuation.get_index_detail(conn, code)
    if detail is None:
        return None
    result = dict(detail)
    result["constituents"] = repositories_valuation.get_index_constituents(conn, code)
    result["tracker_funds"] = repositories_valuation.get_index_tracker_funds(conn, code)
    return result


# ---------------------------------------------------------------------------
# 路由注册
# ---------------------------------------------------------------------------
def register_routes(app: FastAPI) -> None:
    """注册 ``/api/v1`` 只读端点（由 ``main.py`` 调用）。"""
    app.add_exception_handler(ApiError, _api_error_handler)
    app.add_exception_handler(RequestValidationError, _request_validation_handler)

    quotes_dep = _build_auth_dependency("quotes")
    valuation_dep = _build_auth_dependency("valuation")
    percentile_dep = _build_auth_dependency("percentile")

    # ---- 行情日线 --------------------------------------------------------
    @app.get("/api/v1/market/daily", tags=["public-api"])
    def market_daily(
        request: Request,
        codes: Optional[str] = Query(None, description="逗号分隔代码，最多 50 个"),
        start: Optional[str] = Query(None, description="ISO 日期 YYYY-MM-DD"),
        end: Optional[str] = Query(None, description="ISO 日期 YYYY-MM-DD"),
        adjust: str = Query("bfq", description="复权口径 bfq/hfq（qfq 已停用）"),
        limit: int = Query(MAX_ROWS, description="最大返回行数，上限 50000"),
        output_format: Optional[str] = Query(
            None, alias="format", description="json 或 csv"
        ),
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
            rows, unknown, truncated = _fetch_market_daily(
                conn,
                codes=code_list,
                adjust=adjust_value,
                start=start_date,
                end=end_date,
                limit=row_limit,
            )
        if unknown:
            raise ApiError(
                404,
                "unknown_code",
                f"以下代码不存在或没有该复权口径数据: {', '.join(unknown)}",
                codes=unknown,
            )
        if as_csv:
            return _csv_response(rows, MARKET_DAILY_CSV_COLUMNS, "market_daily.csv")
        return _envelope(
            rows,
            rows=len(rows),
            codes=code_list,
            start=start_date.isoformat() if start_date else None,
            end=end_date.isoformat() if end_date else None,
            adjust=adjust_value,
            limit=row_limit,
            truncated=truncated,
            source="bp_quote_clean",
            # 同一 (code, date) 多源重复时按来源优先级取一条：非备份源优先（东财 > 新浪/腾讯）。
            collapse="dedup_by_symbol_date_source_priority",
        )

    # ---- 指数估值 --------------------------------------------------------
    @app.get("/api/v1/index/valuation", tags=["public-api"])
    def index_valuation(
        request: Request,
        codes: Optional[str] = Query(None, description="逗号分隔指数代码，最多 50 个"),
        start: Optional[str] = Query(None, description="ISO 日期 YYYY-MM-DD"),
        end: Optional[str] = Query(None, description="ISO 日期 YYYY-MM-DD"),
        fields: Optional[str] = Query(
            None,
            description="逗号分隔字段: pe_ttm,pb,dividend_yield_ttm,erp",
        ),
        limit: int = Query(MAX_ROWS, description="最大返回行数，上限 50000"),
        output_format: Optional[str] = Query(
            None, alias="format", description="json 或 csv"
        ),
        _token: Any = Depends(valuation_dep),
    ):
        code_list = _parse_codes(codes)
        field_list = _parse_list_param(
            fields,
            default=DEFAULT_VALUATION_FIELDS,
            allowed=VALUATION_FIELDS,
            field="fields",
        )
        start_date = _parse_iso_date(start, "start")
        end_date = _parse_iso_date(end, "end")
        _validate_range(start_date, end_date)
        row_limit = _validate_limit(limit)
        as_csv = _wants_csv(request, output_format)

        with db.get_conn() as conn:
            rows, unknown, truncated = _fetch_index_valuation(
                conn,
                codes=code_list,
                fields=field_list,
                start=start_date,
                end=end_date,
                limit=row_limit,
            )
        if unknown:
            raise ApiError(
                404,
                "unknown_code",
                f"以下指数代码不存在: {', '.join(unknown)}",
                codes=unknown,
            )
        if as_csv:
            columns = ("code", "date", *field_list)
            return _csv_response(rows, columns, "index_valuation.csv")
        return _envelope(
            rows,
            rows=len(rows),
            codes=code_list,
            fields=field_list,
            start=start_date.isoformat() if start_date else None,
            end=end_date.isoformat() if end_date else None,
            limit=row_limit,
            truncated=truncated,
            source="bp_index_valuation_daily.is_primary",
        )

    # ---- 指数分位 --------------------------------------------------------
    @app.get("/api/v1/index/percentile", tags=["public-api"])
    def index_percentile(
        request: Request,
        codes: Optional[str] = Query(None, description="逗号分隔指数代码，最多 50 个"),
        metrics: Optional[str] = Query(
            None, description="逗号分隔指标，默认 pe_ttm"
        ),
        windows: Optional[str] = Query(
            None, description="逗号分隔窗口: 5y,10y,all，默认 5y"
        ),
        limit: int = Query(MAX_ROWS, description="最大返回行数，上限 50000"),
        output_format: Optional[str] = Query(
            None, alias="format", description="json 或 csv"
        ),
        _token: Any = Depends(percentile_dep),
    ):
        code_list = _parse_codes(codes)
        metric_list = _parse_list_param(
            metrics,
            default=("pe_ttm",),
            allowed=PERCENTILE_METRICS,
            field="metrics",
        )
        window_list = _parse_list_param(
            windows,
            default=("5y",),
            allowed=PERCENTILE_WINDOWS,
            field="windows",
        )
        row_limit = _validate_limit(limit)
        as_csv = _wants_csv(request, output_format)

        with db.get_conn() as conn:
            rows, unknown, truncated = _fetch_index_percentile(
                conn,
                codes=code_list,
                metrics=metric_list,
                windows=window_list,
                limit=row_limit,
            )
        if unknown:
            raise ApiError(
                404,
                "unknown_code",
                f"以下指数代码不存在: {', '.join(unknown)}",
                codes=unknown,
            )
        if as_csv:
            return _csv_response(rows, PERCENTILE_CSV_COLUMNS, "index_percentile.csv")
        return _envelope(
            rows,
            rows=len(rows),
            codes=code_list,
            metrics=metric_list,
            windows=window_list,
            limit=row_limit,
            truncated=truncated,
            source="bp_index_percentile",
        )

    # ---- 指数详情 --------------------------------------------------------
    @app.get("/api/v1/index/detail", tags=["public-api"])
    def index_detail(
        request: Request,
        code: Optional[str] = Query(None, description="指数代码，如 930641"),
        output_format: Optional[str] = Query(
            None, alias="format", description="json 或 csv"
        ),
        _token: Any = Depends(valuation_dep),
    ):
        if code is None or not code.strip():
            raise ApiError(400, "missing_parameter", "code 为必填参数")
        index_code = code.strip()
        as_csv = _wants_csv(request, output_format)

        with db.get_conn() as conn:
            detail = _load_index_detail(conn, index_code)
        if detail is None:
            raise ApiError(
                404,
                "index_not_found",
                f"指数 {index_code} 不存在",
                index_code=index_code,
            )

        if as_csv:
            columns = list(detail.keys())
            return _csv_response([detail], columns, "index_detail.csv")
        return _envelope(
            detail,
            rows=1,
            source="bp_index_master",
        )

    # ---- 10Y 国债收益率 --------------------------------------------------
    @app.get("/api/v1/market/bond-yield", tags=["public-api"])
    def bond_yield(
        request: Request,
        start: Optional[str] = Query(None, description="ISO 日期 YYYY-MM-DD"),
        end: Optional[str] = Query(None, description="ISO 日期 YYYY-MM-DD"),
        limit: int = Query(MAX_ROWS, description="最大返回行数，上限 50000"),
        output_format: Optional[str] = Query(
            None, alias="format", description="json 或 csv"
        ),
        _token: Any = Depends(valuation_dep),
    ):
        start_date = _parse_iso_date(start, "start")
        end_date = _parse_iso_date(end, "end")
        _validate_range(start_date, end_date)
        row_limit = _validate_limit(limit)
        as_csv = _wants_csv(request, output_format)

        with db.get_conn() as conn:
            rows, truncated = _fetch_bond_yield(
                conn,
                start=start_date,
                end=end_date,
                limit=row_limit,
            )
        if as_csv:
            return _csv_response(rows, BOND_YIELD_CSV_COLUMNS, "bond_yield.csv")
        return _envelope(
            rows,
            rows=len(rows),
            series_code=BOND_SERIES_CODE,
            start=start_date.isoformat() if start_date else None,
            end=end_date.isoformat() if end_date else None,
            limit=row_limit,
            truncated=truncated,
            source="bp_macro_series",
        )
