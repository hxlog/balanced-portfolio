"""指数估值落库编排：抓取 → 主数据 → 日频估值 → 历史序列 → 分位预计算。

契约见 ``docs/index-valuation/15-p0-contracts.md`` §3。

要点：
- 单指数失败不中断整批：每个指数的日频/序列/分位写入放在独立 savepoint 内，
  失败则该指数本次 0 行，错误写入摘要 ``errors``；
- 幂等：全部写入走 ``repositories_valuation`` 的 ``ON CONFLICT DO UPDATE``；
- 分位唯一入口：``bp_api.quant.valuation.window_slice + summarize``；
- ERP 严格遵守「同日」：仅当股息率历史点与十年期国债收益率同日时才生成，
  不做 forward-fill。周频 ERP 与当日 ERP 都写入 ``bp_index_valuation_series``，
  否则分位无法从库内复现。
"""

from __future__ import annotations

import math
import time
from contextlib import contextmanager
from datetime import date, datetime
from typing import Any, Callable, Iterator, Mapping, Optional, Sequence

import psycopg

from bp_api.quant.valuation import erp as quant_erp
from bp_api.quant.valuation import summarize, window_slice
from bp_api.repositories_valuation import (
    upsert_constituents,
    upsert_fund_master,
    upsert_stock_master,
    upsert_tracker_funds,
    CALC_SRC_PINGAN,
    INDEX_MARKETS,
    fetch_series,
    upsert_index_master,
    upsert_percentiles,
    upsert_valuation_daily,
    upsert_valuation_series,
)

from .valuation_pingan import fetch_all, normalize_index_row

# 分位重算的唯一口径：4 指标 × 3 窗口。
PERCENTILE_METRIC_ORDER = ("pe_ttm", "pb", "dividend_yield_ttm", "erp")
PERCENTILE_WINDOW_ORDER = ("5y", "10y", "all")

_LEVEL_MAP = {
    "低估": "低估",
    "低": "低估",
    "较低": "低估",
    "中性": "中性",
    "中": "中性",
    "中等": "中性",
    "高估": "高估",
    "高": "高估",
    "较高": "高估",
}

_MARKET_SUFFIX = {
    ".CSI": "CSI",
    ".SH": "SH",
    ".SZ": "SZ",
    ".CNI": "CNI",
    ".HK": "HK",
    ".US": "US",
}

# 写入 daily.raw 的字段：保留画像/成分/跟踪基金/年度序列，避免重复存压缩串。
_RAW_KEYS = (
    "vendor_code",
    "index_code",
    "market",
    "name",
    "index_type",
    "intro",
    "pe_ratio",
    "pe_percentile",
    "pe_level",
    "pb_ratio",
    "pb_percentile",
    "pb_level",
    "is_pb",
    "dividend_rate",
    "dividend_percentile",
    "dividend_level",
    "high_dividend",
    "low_dividend",
    "peg",
    "peg_level",
    "roe",
    "roe_level",
    "roe_ttm",
    "roe_growth",
    "roe_growth_percent",
    "volatility",
    "volatility_level",
    "sharp_ratio",
    "sharp_level",
    "bond10",
    "high_pe",
    "low_pe",
    "rise_last_day",
    "rise_week",
    "rise_month",
    "rise_3_months",
    "rise_6_months",
    "rise_year",
    "income_yoy",
    "profit_yoy",
    "market_show",
    "update_date",
    "stock_list",
    "etf_fund",
    "otc_fund",
    "roe_trace",
    "profit_trace",
    "profit_expectation",
)


@contextmanager
def _savepoint(conn: psycopg.Connection, name: str) -> Iterator[None]:
    """显式 SAVEPOINT：失败回滚到保存点，成功释放；**绝不 commit**。

    不能用 ``conn.transaction()``：当连接空闲（autocommit=False 且尚无事务）时，
    它会在退出时提交整个事务，破坏调用方的事务边界。
    """
    with conn.cursor() as cur:
        cur.execute(f'SAVEPOINT "{name}"')
    try:
        yield
    except Exception:
        with conn.cursor() as cur:
            cur.execute(f'ROLLBACK TO SAVEPOINT "{name}"')
            cur.execute(f'RELEASE SAVEPOINT "{name}"')
        raise
    else:
        with conn.cursor() as cur:
            cur.execute(f'RELEASE SAVEPOINT "{name}"')


def _text(value: Any) -> Optional[str]:
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def _float(value: Any) -> Optional[float]:
    if value is None or isinstance(value, bool):
        return None
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if math.isfinite(number) else None


def _positive(value: Any) -> Optional[float]:
    number = _float(value)
    return number if number is not None and number > 0 else None


def _bounded(value: Any, low: float, high: float) -> Optional[float]:
    number = _float(value)
    if number is None or not low <= number <= high:
        return None
    return number


def _level(value: Any) -> Optional[str]:
    text = _text(value)
    return _LEVEL_MAP.get(text) if text else None


def _as_date(value: Any) -> Optional[date]:
    if value is None:
        return None
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    if isinstance(value, str):
        text = value.strip()
        for fmt in ("%Y%m%d", "%Y-%m-%d"):
            try:
                return datetime.strptime(text, fmt).date()
            except ValueError:
                continue
    return None


def _merge_rows(*groups: Sequence[Mapping[str, Any]]) -> dict[str, dict]:
    """按 index_code 合并 INDEX_DATA（universe）与 INDEX_DATA_V2（detail）。

    非空值覆盖空值；空值不覆盖已有数据。detail 通常字段更全，放在后一组。
    """
    merged: dict[str, dict] = {}
    for group in groups:
        for raw in group or []:
            try:
                normalized = normalize_index_row(raw)
            except Exception:  # noqa: BLE001 - 单行脏数据不应拖垮整批
                continue
            index_code = _text(normalized.get("index_code"))
            if not index_code:
                continue
            current = merged.setdefault(index_code, {})
            for key, value in normalized.items():
                if value is None or value == [] or value == "":
                    current.setdefault(key, value)
                else:
                    current[key] = value
    return merged


def _description_by_code(rows: Sequence[Mapping[str, Any]]) -> dict[str, dict]:
    """A_INDEX_DESCRIPTION 的 code 是 GUID，必须用 sInfoWindCode 映射到指数代码。"""
    result: dict[str, dict] = {}
    for raw in rows or []:
        wind_code = _text(raw.get("sInfoWindCode"))
        if not wind_code:
            continue
        index_code, _, suffix = wind_code.partition(".")
        index_code = index_code.strip()
        if not index_code:
            continue
        result[index_code] = {
            "wind_code": wind_code,
            "market": _MARKET_SUFFIX.get(f".{suffix.upper()}") if suffix else None,
            "publisher": _text(raw.get("sInfoPublisher")),
            "base_date": _as_date(raw.get("sInfoIndexBaseper")),
            "base_point": _float(raw.get("sInfoIndexBasept")),
            "income_method": _text(raw.get("sInfoIncomeMethod")),
            "weight_method": _text(raw.get("weightTypeName"))
            or _text(raw.get("sInfoIndexWeightsrule")),
            "intro": _text(raw.get("indexIntro")),
        }
    return result


def _bond10_by_date(rows: Sequence[Mapping[str, Any]]) -> dict[date, float]:
    result: dict[date, float] = {}
    for raw in rows or []:
        trade_date = _as_date(raw.get("tradeDt"))
        value = _float(raw.get("bAnalyield"))
        if trade_date is not None and value is not None:
            result[trade_date] = value
    return result


def _build_master(index_code: str, normalized: Mapping[str, Any], desc: Mapping[str, Any]) -> dict:
    market = _text(normalized.get("market")) or _text(desc.get("market"))
    name = _text(normalized.get("name"))
    if not market:
        raise ValueError("missing market")
    if market not in INDEX_MARKETS:
        raise ValueError(f"unsupported market: {market}")
    if not name:
        raise ValueError("missing name")
    return {
        "index_code": index_code,
        "market": market,
        "wind_code": desc.get("wind_code"),
        "name": name,
        "short_name": None,
        "index_type": _text(normalized.get("index_type")),
        "publisher": desc.get("publisher"),
        "base_date": desc.get("base_date"),
        "base_point": desc.get("base_point"),
        "income_method": desc.get("income_method"),
        "weight_method": desc.get("weight_method"),
        "intro": _text(normalized.get("intro")) or desc.get("intro"),
        "is_active": True,
        "is_tracked": True,
    }


def _daily_values(
    normalized: Mapping[str, Any],
) -> tuple[Optional[float], Optional[float], Optional[float], Optional[float], Optional[float]]:
    """返回 (pe_ttm, pb, dividend_yield_ttm, bond10y, erp)。"""
    pe = _positive(normalized.get("pe_ratio"))
    pb = _positive(normalized.get("pb_ratio"))
    dividend = _bounded(normalized.get("dividend_rate"), -100.0, 100.0)
    bond10y = _float(normalized.get("bond10"))
    erp_value = None
    if dividend is not None and bond10y is not None:
        erp_value = quant_erp(dividend / 100.0, bond10y)
    return pe, pb, dividend, bond10y, erp_value


def _raw_payload(normalized: Mapping[str, Any]) -> dict:
    return {key: normalized.get(key) for key in _RAW_KEYS if key in normalized}


def _build_stock_rows(index_code: str, normalized: Mapping[str, Any], trade_date: date) -> tuple[list[dict], list[dict]]:
    """(股票主数据行, 成分股行)。平安 stockList 只给前 30 大权重。"""
    stocks = normalized.get("stock_list") or []
    stock_rows: list[dict] = []
    constituent_rows: list[dict] = []
    seen: set[str] = set()
    for rank, item in enumerate(stocks, start=1):
        if not isinstance(item, Mapping):
            continue
        code = _text(item.get("stock_code"))
        market = _text(item.get("market"))
        name = _text(item.get("name"))
        if not code or market not in ("SH", "SZ", "BJ") or not name:
            continue
        if code in seen:
            continue
        seen.add(code)
        stock_rows.append({"stock_code": code, "market": market, "name": name})
        constituent_rows.append({
            "index_code": index_code,
            "effective_date": trade_date,
            "stock_code": code,
            "weight": _bounded(item.get("weight"), 0, 100),
            "rank": rank,
            "source": CALC_SRC_PINGAN,
        })
    return stock_rows, constituent_rows


def _build_fund_rows(
    merged: Mapping[str, Mapping[str, Any]],
    tracker_raw: Sequence[Mapping[str, Any]],
    trade_date: date,
) -> tuple[list[dict], list[dict]]:
    """(基金主数据行, 指数-基金跟踪关系行)。"""
    fund_meta: dict[str, dict] = {}
    for row in tracker_raw:
        if not isinstance(row, Mapping):
            continue
        code = _text(row.get("fundCode"))
        if not code:
            continue
        raw_position = row.get("positionDTO")
        position = raw_position if isinstance(raw_position, Mapping) else {}
        fund_meta[code] = {
            "fund_code": code,
            "name": _text(row.get("ommName")) or code,
            "company_name": _text(row.get("companyName")),
            "risk_grade": _text(row.get("riskGrade")),
            "aum": _to_float(position.get("fnvsum")) if position else None,
        }

    master_rows: list[dict] = []
    tracker_rows: list[dict] = []
    for index_code, normalized in merged.items():
        for fund_code in normalized.get("etf_fund") or []:
            meta = fund_meta.get(str(fund_code))
            if meta is None:
                continue
            master_rows.append({k: meta[k] for k in ("fund_code", "name", "company_name", "risk_grade")})
            tracker_rows.append({
                "index_code": index_code,
                "fund_code": meta["fund_code"],
                "trade_date": trade_date,
                "aum": meta["aum"],
                "source": CALC_SRC_PINGAN,
            })
    return master_rows, tracker_rows

def _build_daily(index_code: str, normalized: Mapping[str, Any], trade_date: date) -> dict:
    pe, pb, dividend, bond10y, erp_value = _daily_values(normalized)
    roe = _float(normalized.get("roe_ttm"))
    if roe is None:
        roe = _float(normalized.get("roe"))
    return {
        "index_code": index_code,
        "trade_date": trade_date,
        "calc_src": CALC_SRC_PINGAN,
        "pe_ttm": pe,
        "pe_static": None,
        "pb": pb,
        "dividend_yield_ttm": dividend,
        "dividend_yield_lyr": None,
        "roe_ttm": roe,
        "roa_ttm": None,
        "bond10y": bond10y,
        "erp": erp_value,
        "pe_basis": "vendor_default",
        "pb_basis": "vendor_default",
        "div_basis": "ttm",
        "level_pe": _level(normalized.get("pe_level")),
        "level_pb": _level(normalized.get("pb_level")),
        "level_dividend": _level(normalized.get("dividend_level")),
        "is_primary": True,
        "raw": _raw_payload(normalized),
    }


def _build_series(
    index_code: str,
    normalized: Mapping[str, Any],
    trade_date: date,
    bond10_by_date: Mapping[date, float],
) -> list[dict]:
    """周频 pe/pb/股息率 + 同日 ERP 历史，再追加当日日频点。

    以 ``(trade_date, metric)`` 去重：当日点覆盖同日周频点，避免同一批
    ``ON CONFLICT`` 出现重复键。
    """
    rows: dict[tuple[date, str], dict] = {}

    def put(day: Any, metric: str, value: Any, is_weekly: bool) -> None:
        if not isinstance(day, date) or day > trade_date:
            return
        number = _float(value)
        if number is None:
            return
        # 与日频表 CHECK 同口径：PE/PB 必须为正，股息率限制在 [-100, 100]。
        if metric in {"pe_ttm", "pe_static", "pb"} and number <= 0:
            return
        if metric in {"dividend_yield_ttm", "dividend_yield_lyr"} and not (
            -100.0 <= number <= 100.0
        ):
            return
        rows[(day, metric)] = {
            "index_code": index_code,
            "trade_date": day,
            "metric": metric,
            "calc_src": CALC_SRC_PINGAN,
            "value": number,
            "is_weekly": is_weekly,
        }

    for day, value in normalized.get("pe_bar") or []:
        put(day, "pe_ttm", value, True)
    for day, value in normalized.get("pb_bar") or []:
        put(day, "pb", value, True)

    dividend_history = normalized.get("dividend_history") or []
    for day, value in dividend_history:
        put(day, "dividend_yield_ttm", value, True)
    for day, value in dividend_history:
        if not isinstance(day, date) or day > trade_date:
            continue
        bond10y = bond10_by_date.get(day)
        dividend = _float(value)
        if bond10y is None or dividend is None:
            continue
        erp_value = quant_erp(dividend / 100.0, bond10y)
        if erp_value is not None:
            put(day, "erp", erp_value, True)

    pe, pb, dividend, _bond10y, erp_value = _daily_values(normalized)
    for metric, value in (
        ("pe_ttm", pe),
        ("pb", pb),
        ("dividend_yield_ttm", dividend),
        ("erp", erp_value),
    ):
        if value is not None:
            put(trade_date, metric, value, False)

    return [rows[key] for key in sorted(rows)]


def _build_percentiles(
    conn: psycopg.Connection, index_code: str, trade_date: date
) -> list[dict]:
    rows: list[dict] = []
    for metric in PERCENTILE_METRIC_ORDER:
        series = fetch_series(
            conn, index_code, metric, CALC_SRC_PINGAN, None, trade_date
        )
        for window_key in PERCENTILE_WINDOW_ORDER:
            stats = summarize(window_slice(series, trade_date, window_key))
            rows.append(
                {
                    "index_code": index_code,
                    "as_of_date": trade_date,
                    "metric": metric,
                    "window_key": window_key,
                    "calc_src": CALC_SRC_PINGAN,
                    "pct": stats["pct"],
                    "mean": stats["mean"],
                    "sd": stats["sd"],
                    "p20": stats["p20"],
                    "p50": stats["p50"],
                    "p80": stats["p80"],
                    "min_value": stats["min"],
                    "max_value": stats["max"],
                    "sample_size": stats["sample_size"],
                }
            )
    return rows


def _summary(
    as_of: date,
    indices: int,
    valuation_rows: int,
    series_rows: int,
    percentile_rows: int,
    errors: list[str],
    started_at: float,
) -> dict:
    return {
        "as_of": as_of,
        "indices": indices,
        "valuation_rows": valuation_rows,
        "series_rows": series_rows,
        "percentile_rows": percentile_rows,
        "errors": errors,
        "duration_ms": max(0, int((time.perf_counter() - started_at) * 1000)),
    }


def run_valuation_ingest(
    conn: psycopg.Connection,
    as_of: Optional[date] = None,
    fetch: Callable[[], dict] = fetch_all,
) -> dict:
    """抓取 → 落库 → 重算分位，返回摘要。

    单个指数失败不影响其他指数；整体抓取异常也会落成 ``errors`` 并返回零计数摘要。
    本函数不 commit，事务由调用方提交。
    """
    started_at = time.perf_counter()
    target_as_of = as_of.date() if isinstance(as_of, datetime) else as_of
    errors: list[str] = []
    indices = 0
    valuation_rows = 0
    series_rows = 0
    percentile_rows = 0

    try:
        payload = fetch() or {}
    except Exception as exc:  # noqa: BLE001 - 抓取失败返回摘要，交给调度器告警
        return _summary(
            target_as_of or date.today(),
            0,
            0,
            0,
            0,
            [f"fetch: {exc}"],
            started_at,
        )

    errors.extend(payload.get("errors") or [])

    merged = _merge_rows(
        payload.get("index_universe") or [],
        payload.get("index_detail") or [],
    )
    descriptions = _description_by_code(payload.get("index_description") or [])
    bond10_by_date = _bond10_by_date(payload.get("bond10_history") or [])

    update_dates = [
        value
        for value in (row.get("update_date") for row in merged.values())
        if isinstance(value, date)
    ]
    summary_as_of = target_as_of or (max(update_dates) if update_dates else date.today())

    master_rows: list[dict] = []
    valid_codes: list[str] = []
    for index_code in sorted(merged):
        try:
            master_rows.append(
                _build_master(
                    index_code,
                    merged[index_code],
                    descriptions.get(index_code, {}),
                )
            )
            valid_codes.append(index_code)
        except Exception as exc:  # noqa: BLE001 - 单指数失败隔离
            errors.append(f"{index_code}: {exc}")

    if master_rows:
        # uq_index_master_wind 是唯一索引：同一批出现重复 wind_code 时只保留首个，
        # 否则一条脏数据会拖垮整批主数据 upsert。
        seen_wind: set[str] = set()
        for row in master_rows:
            wind_code = row.get("wind_code")
            if not wind_code:
                continue
            if wind_code in seen_wind:
                row["wind_code"] = None
            else:
                seen_wind.add(wind_code)

        try:
            with _savepoint(conn, "valuation_master"):
                indices = upsert_index_master(conn, master_rows)
        except Exception as exc:  # noqa: BLE001 - 批量失败降级为逐指数隔离
            errors.append(f"master batch: {exc}")
            indices = 0
            master_ok: set[str] = set()
            for row in master_rows:
                try:
                    with _savepoint(conn, "valuation_master_row"):
                        indices += upsert_index_master(conn, [row])
                    master_ok.add(row["index_code"])
                except Exception as row_exc:  # noqa: BLE001
                    errors.append(f"{row['index_code']}: {row_exc}")
            valid_codes = [code for code in valid_codes if code in master_ok]

    for index_code in valid_codes:
        normalized = merged[index_code]
        trade_date = target_as_of or normalized.get("update_date")
        if not isinstance(trade_date, date):
            errors.append(f"{index_code}: missing trade_date")
            continue
        try:
            with _savepoint(conn, "valuation_index"):
                valuation_rows += upsert_valuation_daily(
                    conn, [_build_daily(index_code, normalized, trade_date)]
                )
                series_rows += upsert_valuation_series(
                    conn,
                    _build_series(
                        index_code, normalized, trade_date, bond10_by_date
                    ),
                )
                percentile_rows += upsert_percentiles(
                    conn, _build_percentiles(conn, index_code, trade_date)
                )
                stock_rows, constituent_rows = _build_stock_rows(
                    index_code, normalized, trade_date
                )
                upsert_stock_master(conn, stock_rows)
                upsert_constituents(conn, constituent_rows)
        except Exception as exc:  # noqa: BLE001 - 单指数失败隔离
            errors.append(f"{index_code}: {exc}")

    tracker_raw = payload.get("tracker_funds") or []
    if tracker_raw:
        try:
            with _savepoint(conn, "valuation_funds"):
                fund_master_rows, tracker_rows = _build_fund_rows(
                    merged, tracker_raw, summary_as_of
                )
                upsert_fund_master(conn, fund_master_rows)
                upsert_tracker_funds(conn, tracker_rows)
        except Exception as exc:  # noqa: BLE001
            errors.append(f"tracker_funds: {exc}")

    return _summary(
        summary_as_of,
        indices,
        valuation_rows,
        series_rows,
        percentile_rows,
        errors,
        started_at,
    )
