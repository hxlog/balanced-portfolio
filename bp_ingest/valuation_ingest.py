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
from datetime import date, datetime, timedelta
from typing import Any, Callable, Iterator, Mapping, Optional, Sequence

import psycopg

from bp_api.quant.valuation import erp as quant_erp
from bp_api.quant.valuation import min_sample_for, summarize, window_slice
from bp_api.repositories_valuation import (
    refresh_valuation_latest,
    upsert_macro_series,
    upsert_constituents,
    upsert_fund_master,
    upsert_fund_performance,
    upsert_quote_health,
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

# 分位重算的唯一口径：4 指标 × 5 窗口（1/3/5/10 年 + 全历史）。
PERCENTILE_METRIC_ORDER = ("pe_ttm", "pb", "dividend_yield_ttm", "erp")
PERCENTILE_WINDOW_ORDER = ("1y", "3y", "5y", "10y", "all")

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
    # 中证官网 xls 的日期列经 pandas 读取后可能是 YYYYMMDD 整数
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        try:
            value = str(int(value))
        except (TypeError, ValueError):
            return None
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


def _build_macro_rows(rows: Sequence[Mapping[str, Any]]) -> list[dict]:
    """BOND10_TREND -> bp_macro_series 行（十年期国债到期收益率，单位 %）。"""
    out: list[dict] = []
    for raw in rows or []:
        trade_date = _as_date(raw.get("tradeDt"))
        value = _float(raw.get("bAnalyield"))
        if trade_date is None or value is None:
            continue
        out.append(
            {
                "series_code": "cn_10y_yield",
                "trade_date": trade_date,
                "value": value,
                "unit": "%",
                "source": CALC_SRC_PINGAN,
            }
        )
    return out

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
) -> tuple[list[dict], list[dict], list[dict]]:
    """(基金主数据行, 指数-基金跟踪关系行, 基金业绩行)。"""
    fund_meta: dict[str, dict] = {}
    perf_meta: dict[str, dict] = {}
    for row in tracker_raw:
        if not isinstance(row, Mapping):
            continue
        code = _text(row.get("fundCode"))
        if not code:
            continue
        raw_position = row.get("positionDTO")
        position = raw_position if isinstance(raw_position, Mapping) else {}
        nav_raw = position.get("newFundDrFundnv")
        nav = nav_raw if isinstance(nav_raw, Mapping) else {}
        sessions = position.get("drFmpfmanceDTOS")
        manager = None
        if isinstance(sessions, list) and sessions and isinstance(sessions[0], Mapping):
            manager = _text(sessions[0].get("manager"))
        aum = _float(position.get("fnvsum"))
        fund_meta[code] = {
            "fund_code": code,
            "name": _text(row.get("ommName")) or code,
            "company_name": _text(row.get("companyName")),
            "risk_grade": _text(row.get("riskGrade")),
            "manager": manager,
            "fund_type": _text(row.get("investmentType")) or _text(row.get("fundCSRCType")),
            "management_fee": None,
            "custody_fee": None,
            "established_date": None,
            "fund_scale": aum,
            "aum": aum,
        }
        perf_meta[code] = {
            "fund_code": code,
            "as_of": trade_date,
            "aum": aum,
            "ret_1m": _float(nav.get("nvgr4w")),
            "ret_3m": _float(nav.get("nvgr13w")),
            "ret_6m": _float(nav.get("nvgr26w")),
            "ret_12m": _float(nav.get("nvgr52w")),
            "ret_2y": _float(nav.get("yield2ya")),
            "ret_3y": _float(nav.get("yield3ya")),
            "ret_5y": _float(nav.get("yield5ya")),
            "ytd": _float(nav.get("nvgrty")) or _float(nav.get("yieldly")),
            "manager": manager,
        }

    master_rows: list[dict] = []
    tracker_rows: list[dict] = []
    perf_rows: list[dict] = []
    for index_code, normalized in merged.items():
        for fund_code in normalized.get("etf_fund") or []:
            meta = fund_meta.get(str(fund_code))
            if meta is None:
                continue
            master_rows.append({
                k: meta[k]
                for k in (
                    "fund_code", "name", "company_name", "risk_grade", "manager",
                    "fund_type", "management_fee", "custody_fee", "established_date",
                    "fund_scale",
                )
            })
            if meta["fund_code"] in perf_meta:
                perf_rows.append(perf_meta[meta["fund_code"]])
            tracker_rows.append({
                "index_code": index_code,
                "fund_code": meta["fund_code"],
                "trade_date": trade_date,
                "aum": meta["aum"],
                "source": CALC_SRC_PINGAN,
            })
    return master_rows, tracker_rows, perf_rows

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
    conn: psycopg.Connection,
    index_code: str,
    trade_date: date,
    calc_src: str = CALC_SRC_PINGAN,
) -> list[dict]:
    rows: list[dict] = []
    for metric in PERCENTILE_METRIC_ORDER:
        series = fetch_series(conn, index_code, metric, calc_src, None, trade_date)
        for window_key in PERCENTILE_WINDOW_ORDER:
            stats = summarize(window_slice(series, trade_date, window_key), min_sample_for(window_key))
            rows.append(
                {
                    "index_code": index_code,
                    "as_of_date": trade_date,
                    "metric": metric,
                    "window_key": window_key,
                    "calc_src": calc_src,
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


# ---------------------------------------------------------------------------
# 中证官网 fallback：平安 universe 未覆盖的指数（如 000985 中证全指）
#
# 平安估值源（INDEX_DATA/INDEX_DATA_V2）的 521 只 universe 不含中证全指 000985，
# 且用 SH000985/ZI000985 等供应商代码也查不到。这里用中证指数官网的免费静态文件补：
#   - indicator/{code}indicator.xls：滚动 20 个交易日的 PE(静态/滚动) + 股息率(LYR/TTM)；
#   - perf/{code}perf.xls：滚动 24 个交易日 OHLC（每日增量）；
#   - index-perf JSON API：首次接入时回补 2017 年以来的完整日线（仅一次，之后走 perf.xls）。
#
# 口径与来源记录：
#   - 估值日频/序列 calc_src = csindex_value，is_primary=True（该指数没有平安主口径，
#     csindex 即其主口径）；ERP 用同日 bp_macro_series.cn_10y_yield 计算，不做 forward-fill；
#   - 行情写 bp_index_quote_daily，source = csindex_perf，adjust = bfq；
#   - **PB 不可得**：中证官网估值文件只有 PE/股息率，没有 PB。这里不插值、不用其他
#     指数/其他口径冒充，PB 留 NULL 并在 raw 里标记 pb_available=False（页面降级为
#     「数据建设中」），待后续出现可授权的官方 PB 源再补。
# ---------------------------------------------------------------------------

FALLBACK_INDEX_CODES = ("000985",)
CSINDEX_OSS_BASE = (
    "https://oss-ch.csindex.com.cn/static/html/csindex/public/uploads/file/autofile"
)
CSINDEX_PERF_API = "https://www.csindex.com.cn/csindex-home/perf/index-perf"
CSINDEX_REFERER = "https://www.csindex.com.cn/"
CSINDEX_UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/120.0 Safari/537.36"
)
CALC_SRC_CSINDEX = "csindex_value"
CALC_SRC_CSINDEX_PERF = "csindex_perf"
#: 腾讯指数日 K（cn_index_tx 已注册）；作为 fallback 指数的行情主源
CALC_SRC_CN_INDEX_TX = "cn_index_tx"
# fallback 指数的静态主数据（官网指数概况；迁移 80 里也有同样的 000985 行，
# 这里 upsert 一遍保证「迁移未应用的库/新库」也能正常落库）
CSINDEX_MASTER_META: dict[str, dict] = {
    "000985": {
        "index_code": "000985",
        "market": "CSI",
        "wind_code": "000985.SH",
        "name": "中证全指",
        "short_name": "中证全指",
        "index_type": "宽基",
        "publisher": "中证指数有限公司",
        "base_date": date(2004, 12, 31),
        "base_point": 1000.0,
        "income_method": "价格指数",
        "weight_method": "调整市值加权",
        "intro": "中证全指指数由全部 A 股中剔除 ST、*ST 及上市未满一定期限的证券后组成，反映 A 股市场整体表现。",
        "is_active": True,
        "is_tracked": True,
    }
}


def _csindex_get(url: str, params: Optional[dict] = None, timeout: float = 25.0):
    """带硬化指纹会话的 GET（失败回退普通 requests；测试可 monkeypatch）。"""
    import requests

    try:  # pragma: no cover - 硬化会话是可选增强
        from .http_session import install_hardened_session

        install_hardened_session()
    except Exception:  # noqa: BLE001
        pass
    return requests.get(
        url,
        params=params,
        headers={"User-Agent": CSINDEX_UA, "Referer": CSINDEX_REFERER},
        timeout=timeout,
    )


def _csindex_column(frame, *candidates: str) -> Optional[str]:
    for name in frame.columns:
        text = str(name)
        if any(candidate in text for candidate in candidates):
            return name
    return None


def _parse_csindex_indicator(content: bytes) -> list[dict]:
    """解析 indicator.xls：columns = 日期/市盈率1/市盈率2/股息率1/股息率2。"""
    import io

    import pandas as pd

    frame = pd.read_excel(io.BytesIO(content))
    date_col = _csindex_column(frame, "日期Date", "日期")
    pe1_col = _csindex_column(frame, "市盈率1")
    pe2_col = _csindex_column(frame, "市盈率2")
    div1_col = _csindex_column(frame, "股息率1")
    div2_col = _csindex_column(frame, "股息率2")
    if not date_col:
        return []
    rows: list[dict] = []
    for _, raw in frame.iterrows():
        trade_date = _as_date(raw.get(date_col))
        if trade_date is None:
            continue
        rows.append(
            {
                "trade_date": trade_date,
                "pe_static": _positive(raw.get(pe1_col)) if pe1_col else None,
                "pe_ttm": _positive(raw.get(pe2_col)) if pe2_col else None,
                "dividend_yield_lyr": _bounded(raw.get(div1_col), -100.0, 100.0)
                if div1_col
                else None,
                "dividend_yield_ttm": _bounded(raw.get(div2_col), -100.0, 100.0)
                if div2_col
                else None,
            }
        )
    rows.sort(key=lambda item: item["trade_date"])
    return rows


def _parse_csindex_perf_xls(content: bytes) -> tuple[str, list[dict]]:
    """解析 perf.xls（滚动 24 个交易日 OHLC）为行情行。"""
    import io

    import pandas as pd
    from .db import QuoteRow

    frame = pd.read_excel(io.BytesIO(content))
    date_col = _csindex_column(frame, "日期Date", "日期")
    close_col = _csindex_column(frame, "收盘Close", "收盘")
    if not date_col or not close_col:
        return "", []
    open_col = _csindex_column(frame, "开盘Open", "开盘")
    high_col = _csindex_column(frame, "最高High", "最高")
    low_col = _csindex_column(frame, "最低Low", "最低")
    pct_col = _csindex_column(frame, "涨跌幅")
    vol_col = _csindex_column(frame, "成交量")
    amt_col = _csindex_column(frame, "成交金额")
    name_col = _csindex_column(frame, "指数中文简称Index Chinese Name", "中文简称")

    def _num(row, col):
        if not col:
            return None
        value = row.get(col)
        try:
            number = float(value)
        except (TypeError, ValueError):
            return None
        return number if math.isfinite(number) else None

    name = ""
    if name_col and len(frame):
        name = str(frame[name_col].iloc[0] or "")
    rows: list[dict] = []
    for _, raw in frame.iterrows():
        trade_date = _as_date(raw.get(date_col))
        close = _num(raw, close_col)
        if trade_date is None or close is None:
            continue
        rows.append(
            {
                "row": QuoteRow(
                    trade_date=trade_date,
                    symbol="",
                    source=CALC_SRC_CSINDEX_PERF,
                    category="index",
                    name=name or None,
                    open=_num(raw, open_col),
                    high=_num(raw, high_col),
                    low=_num(raw, low_col),
                    close=close,
                    volume=int(_num(raw, vol_col)) if _num(raw, vol_col) is not None else None,
                    amount=_num(raw, amt_col),
                    turnover_rate=None,
                    pct_change=_num(raw, pct_col),
                    adjust="bfq",
                ),
                "name": name,
            }
        )
    rows.sort(key=lambda item: item["row"].trade_date)
    return name, rows


def _parse_csindex_perf_json(payload: dict) -> tuple[str, list[dict]]:
    """解析 index-perf JSON（全历史日线）为行情行。"""
    from .db import QuoteRow

    items = payload.get("data") or []
    if not isinstance(items, list):
        return "", []
    name = ""
    rows: list[dict] = []
    for item in items:
        if not isinstance(item, Mapping):
            continue
        raw_date = item.get("tradeDate")
        try:
            trade_date = datetime.strptime(str(raw_date), "%Y%m%d").date()
        except (TypeError, ValueError):
            continue
        close = _float(item.get("close"))
        if close is None:
            continue
        name = name or _text(item.get("indexNameCn")) or ""
        volume = _float(item.get("tradingVol"))
        rows.append(
            {
                "row": QuoteRow(
                    trade_date=trade_date,
                    symbol="",
                    source=CALC_SRC_CSINDEX_PERF,
                    category="index",
                    name=name or None,
                    open=_float(item.get("open")),
                    high=_float(item.get("high")),
                    low=_float(item.get("low")),
                    close=close,
                    volume=int(volume) if volume is not None else None,
                    amount=_float(item.get("tradingValue")),
                    turnover_rate=None,
                    pct_change=_float(item.get("changePct")),
                    adjust="bfq",
                ),
                "name": name,
            }
        )
    rows.sort(key=lambda item: item["row"].trade_date)
    return name, rows


def _fetch_tencent_quotes(
    code: str, start: date, end: date
) -> list[dict]:
    """用腾讯 fqkline（bp_ingest.sources._fetch_tx_kline）取指数日 K。

    中证官网 OSS 的 perf.xls 实测停留在 2021-08、index-perf JSON 又被 WAF 间歇
    拦截，故 fallback 指数的行情主源改为腾讯（与 P0-3 指数行情链路同源同口径，
    source = cn_index_tx，adjust = bfq）。失败返回空列表，由调用方记录降级链。
    """
    from .db import QuoteRow
    from .sources import _fetch_tx_kline

    frame = _fetch_tx_kline(code, start, end, "")
    if frame is None or frame.empty:
        return []
    rows: list[dict] = []
    for _, raw in frame.iterrows():
        trade_date = _as_date(raw.get("trade_date"))
        close = _float(raw.get("close"))
        if trade_date is None or close is None:
            continue
        volume = _float(raw.get("volume"))
        rows.append(
            {
                "row": QuoteRow(
                    trade_date=trade_date,
                    symbol=code,
                    source=CALC_SRC_CN_INDEX_TX,
                    category="index",
                    name=None,
                    open=_float(raw.get("open")),
                    high=_float(raw.get("high")),
                    low=_float(raw.get("low")),
                    close=close,
                    volume=int(volume) if volume is not None else None,
                    amount=_float(raw.get("amount")),
                    turnover_rate=None,
                    pct_change=_float(raw.get("pct_change")),
                    adjust="bfq",
                ),
                "name": None,
            }
        )
    return rows


def fetch_csindex_fallback(code: str, full_history: bool = False) -> dict:
    """抓取一只中证官网 fallback 指数的估值/行情原始数据（不写库；测试可替换）。

    返回 {"indicator": [...], "quotes": [...], "name": str, "errors": [...]}；
    quotes 元素是 {"row": QuoteRow, "name": str}，full_history=True 时回补 2017 以来日线。
    行情主源为腾讯 fqkline（source=cn_index_tx），中证官网 JSON/OSS 仅作降级。
    """
    result: dict = {"indicator": [], "quotes": [], "name": "", "errors": []}
    today = date.today()
    # 1) 行情主源：腾讯 fqkline（与 P0-3 指数行情链路同源同口径，source=cn_index_tx）
    quote_start = date(2017, 1, 1) if full_history else today - timedelta(days=45)
    try:
        tencent_rows = _fetch_tencent_quotes(code, quote_start, today)
        if tencent_rows:
            result["quotes"].extend(tencent_rows)
    except Exception as exc:  # noqa: BLE001
        result["errors"].append(f"{code}: tencent_quotes: {type(exc).__name__}: {exc}")

    # 2) 行情降级：中证官网 index-perf JSON（全历史；WAF 拦截时跳过）
    if not result["quotes"]:
        try:
            response = _csindex_get(
                CSINDEX_PERF_API,
                params={
                    "indexCode": code,
                    "startDate": quote_start.strftime("%Y%m%d"),
                    "endDate": today.strftime("%Y%m%d"),
                },
            )
            response.raise_for_status()
            name, rows = _parse_csindex_perf_json(response.json())
            result["name"] = name
            result["quotes"].extend(rows)
        except Exception as exc:  # noqa: BLE001 - 单源失败只记录
            result["errors"].append(f"{code}: csindex_history: {type(exc).__name__}: {exc}")

    # 3) 行情降级：中证官网 OSS perf.xls（实测可能停留在 2021 年，只收近期行，
    #    避免把陈旧价格写进行情表；全历史场景由腾讯/JSON 负责）
    if not result["quotes"]:
        try:
            response = _csindex_get(f"{CSINDEX_OSS_BASE}/perf/{code}perf.xls")
            response.raise_for_status()
            name, rows = _parse_csindex_perf_xls(response.content)
            recent = [
                item
                for item in rows
                if item["row"].trade_date >= today - timedelta(days=45)
            ]
            result["name"] = result["name"] or name
            result["quotes"].extend(recent)
        except Exception as exc:  # noqa: BLE001
            result["errors"].append(f"{code}: perf_xls: {type(exc).__name__}: {exc}")

    # 4) 估值：中证官网 indicator.xls（PE 静态/滚动 + 股息率 LYR/TTM；无 PB）
    try:
        response = _csindex_get(f"{CSINDEX_OSS_BASE}/indicator/{code}indicator.xls")
        response.raise_for_status()
        result["indicator"] = _parse_csindex_indicator(response.content)
    except Exception as exc:  # noqa: BLE001
        result["errors"].append(f"{code}: indicator_xls: {type(exc).__name__}: {exc}")
    return result


def _bond10_by_dates(conn: psycopg.Connection, days: Sequence[date]) -> dict[date, float]:
    if not days:
        return {}
    with conn.cursor() as cur:
        cur.execute(
            "SELECT trade_date, value FROM bp_macro_series"
            " WHERE series_code = 'cn_10y_yield' AND trade_date = ANY(%s)",
            (list(days),),
        )
        return {
            trade_date: value
            for trade_date, value in cur.fetchall()
            if trade_date is not None and _float(value) is not None
        }


def _build_csindex_rows(
    conn: psycopg.Connection,
    index_code: str,
    indicator_rows: Sequence[Mapping[str, Any]],
    max_date: Optional[date],
) -> tuple[list[dict], list[dict], Optional[date]]:
    """中证官网估值 -> (日频估值行, 序列行, 最新日期)；PB 缺失写 NULL。"""
    usable = [
        row
        for row in indicator_rows
        if isinstance(row.get("trade_date"), date)
        and (max_date is None or row["trade_date"] <= max_date)
    ]
    if not usable:
        return [], [], None
    bond10 = _bond10_by_dates(conn, [row["trade_date"] for row in usable])
    daily_rows: list[dict] = []
    series_rows: list[dict] = []
    for row in usable:
        trade_date = row["trade_date"]
        dividend = _bounded(row.get("dividend_yield_ttm"), -100.0, 100.0)
        bond = bond10.get(trade_date)
        erp_value = None
        if dividend is not None and bond is not None:
            erp_value = quant_erp(dividend / 100.0, bond)
        raw = {
            "source": "csindex_official_indicator",
            "pb_available": False,
            "bond10y_same_day": bond,
        }
        daily_rows.append(
            {
                "index_code": index_code,
                "trade_date": trade_date,
                "calc_src": CALC_SRC_CSINDEX,
                "pe_ttm": _positive(row.get("pe_ttm")),
                "pe_static": _positive(row.get("pe_static")),
                "pb": None,
                "dividend_yield_ttm": dividend,
                "dividend_yield_lyr": _bounded(row.get("dividend_yield_lyr"), -100.0, 100.0),
                "roe_ttm": None,
                "roa_ttm": None,
                "bond10y": bond,
                "erp": erp_value,
                "pe_basis": "csindex_official",
                "pb_basis": None,
                "div_basis": "csindex_official_ttm",
                "level_pe": None,
                "level_pb": None,
                "level_dividend": None,
                "is_primary": True,
                "raw": raw,
            }
        )
        for metric, value in (
            ("pe_ttm", _positive(row.get("pe_ttm"))),
            ("pe_static", _positive(row.get("pe_static"))),
            ("dividend_yield_ttm", dividend),
            ("dividend_yield_lyr", _bounded(row.get("dividend_yield_lyr"), -100.0, 100.0)),
            ("erp", erp_value),
        ):
            if value is None:
                continue
            series_rows.append(
                {
                    "index_code": index_code,
                    "trade_date": trade_date,
                    "metric": metric,
                    "calc_src": CALC_SRC_CSINDEX,
                    "value": value,
                    "is_weekly": False,
                }
            )
    return daily_rows, series_rows, usable[-1]["trade_date"]


def _refresh_quote_health(conn: psycopg.Connection, symbols: Sequence[str]) -> None:
    """给 fallback 指数补 bp_index_quote_health（列表页行情状态/滞后用）。"""
    if not symbols:
        return
    with conn.cursor() as cur:
        cur.execute(
            "SELECT max(cal_date) FROM bp_trading_calendar"
            " WHERE is_trading AND cal_date <= current_date"
        )
        row = cur.fetchone()
        expected = row[0] if row else None
        for symbol in symbols:
            cur.execute(
                "SELECT max(trade_date) FROM bp_index_quote_daily"
                " WHERE symbol = %s AND adjust = 'bfq'",
                (symbol,),
            )
            last_row = cur.fetchone()
            last_date = last_row[0] if last_row else None
            lag = 0
            if last_date is None:
                status = "missing"
            elif expected is not None and last_date < expected:
                cur.execute(
                    "SELECT count(*) FROM bp_trading_calendar"
                    " WHERE is_trading AND cal_date > %s AND cal_date <= %s",
                    (last_date, expected),
                )
                lag = int(cur.fetchone()[0] or 0)
                status = "stale" if lag <= 5 else "dead"
            else:
                status = "ok"
            upsert_quote_health(
                conn,
                [
                    {
                        "symbol": symbol,
                        "last_trade_date": last_date,
                        "expected_trade_date": expected,
                        "lag_trading_days": lag,
                        "has_quote": last_date is not None,
                        "status": status,
                    }
                ],
            )


def _run_csindex_fallback(
    conn: psycopg.Connection,
    covered_codes: set[str],
    as_of: Optional[date],
    errors: list[str],
    fetch: Callable[[str, bool], dict] = fetch_csindex_fallback,
) -> dict:
    """对平安未覆盖的 fallback 指数补估值/行情并重算分位，返回计数摘要。

    只处理 FALLBACK_INDEX_CODES 中本次平安 payload 未覆盖的代码；单指数失败写入
    errors 并继续，不阻断整批估值。
    """
    from .db import upsert_quotes

    summary = {
        "indices": 0,
        "valuation_rows": 0,
        "series_rows": 0,
        "percentile_rows": 0,
        "quote_rows": 0,
    }
    for index_code in FALLBACK_INDEX_CODES:
        if index_code in covered_codes:
            continue
        try:
            meta = CSINDEX_MASTER_META.get(index_code)
            if meta is None:
                errors.append(f"csindex_fallback: {index_code}: missing master meta")
                continue
            with conn.cursor() as cur:
                cur.execute(
                    "SELECT count(*) FROM bp_index_quote_daily"
                    " WHERE symbol = %s AND adjust = 'bfq'",
                    (index_code,),
                )
                need_full = int(cur.fetchone()[0] or 0) == 0
                cur.execute(
                    "SELECT count(*) FROM bp_index_master WHERE index_code = %s",
                    (index_code,),
                )
                has_master = int(cur.fetchone()[0] or 0) > 0
            if not has_master:
                upsert_index_master(conn, [meta])
                summary["indices"] += 1

            payload = fetch(index_code, need_full) or {}
            errors.extend(payload.get("errors") or [])

            quote_rows = []
            quote_name = _text(payload.get("name")) or meta["name"]
            for item in payload.get("quotes") or []:
                row = item.get("row") if isinstance(item, Mapping) else None
                if row is None:
                    continue
                # P2：fallback 行情按 as_of 截断，绝不把 as_of 之后的行情写进历史
                # （fetch 抓的是「今天」，但估值任务可能用 --as-of 补历史日期）。
                if as_of is not None and row.trade_date > as_of:
                    continue
                row.symbol = index_code
                row.name = quote_name
                quote_rows.append(row)
            if quote_rows:
                summary["quote_rows"] += upsert_quotes(conn, quote_rows)

            daily_rows, series_rows, latest_date = _build_csindex_rows(
                conn, index_code, payload.get("indicator") or [], as_of
            )
            if daily_rows:
                summary["valuation_rows"] += upsert_valuation_daily(conn, daily_rows)
            if series_rows:
                summary["series_rows"] += upsert_valuation_series(conn, series_rows)
            if latest_date is not None:
                summary["percentile_rows"] += upsert_percentiles(
                    conn,
                    _build_percentiles(
                        conn, index_code, latest_date, calc_src=CALC_SRC_CSINDEX
                    ),
                )
            _refresh_quote_health(conn, [index_code])

            # 最新日频估值是 oracle：fallback 写入后按 as_of 对齐（不回写未来日期）
            if as_of is not None:
                with conn.cursor() as cur:
                    cur.execute(
                        "SELECT count(*) FROM bp_index_valuation_daily"
                        " WHERE index_code = %s AND trade_date > %s",
                        (index_code, as_of),
                    )
                    future = int(cur.fetchone()[0] or 0)
                if future:
                    errors.append(
                        f"csindex_fallback: {index_code}: {future} future rows ignored"
                    )
        except Exception as exc:  # noqa: BLE001 - 单指数失败隔离
            errors.append(f"csindex_fallback: {index_code}: {type(exc).__name__}: {exc}")
    return summary


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
    enable_fallback: Optional[bool] = None,
    fallback_fetch: Optional[Callable[[str, bool], dict]] = None,
    refresh_latest: bool = True,
) -> dict:
    """抓取 → 落库 → 重算分位 → 刷新最新快照，返回摘要。

    单个指数失败不影响其他指数；整体抓取异常也会落成 errors 并返回零计数摘要。
    本函数不 commit，事务由调用方提交。

    - enable_fallback：是否用中证官网补平安未覆盖的指数（000985 等）。None 表示
      自动判断：仅当使用真实 fetch_all 时启用（测试注入 fake fetch 时不联网）；
    - fallback_fetch：fallback 抓取器（签名为 (code, full_history) -> dict），
      默认 fetch_csindex_fallback，测试可注入；
    - refresh_latest：收尾是否刷新 bp_index_valuation_latest 快照（迁移 80 未应用
      的库会自动跳过，不报错）。
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
    bond10_rows = payload.get("bond10_history") or []
    bond10_by_date = _bond10_by_date(bond10_rows)
    # 十年期国债收益率同时落 bp_macro_series，供 /api/v1/market/bond-yield 与前端消费
    if bond10_rows:
        try:
            with _savepoint(conn, "valuation_macro"):
                upsert_macro_series(conn, _build_macro_rows(bond10_rows))
        except Exception as exc:  # noqa: BLE001
            errors.append(f"macro_series: {exc}")

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
                fund_master_rows, tracker_rows, fund_perf_rows = _build_fund_rows(
                    merged, tracker_raw, summary_as_of
                )
                upsert_fund_master(conn, fund_master_rows)
                upsert_fund_performance(conn, fund_perf_rows)
                upsert_tracker_funds(conn, tracker_rows)
        except Exception as exc:  # noqa: BLE001
            errors.append(f"tracker_funds: {exc}")

    # 中证官网 fallback：平安 universe 未覆盖的指数（000985 中证全指）。
    # 默认只在真实抓取（fetch is fetch_all）时启用，测试注入 fake fetch 不联网。
    fallback_summary: Optional[dict] = None
    run_fallback = (
        (fetch is fetch_all) if enable_fallback is None else bool(enable_fallback)
    )
    if run_fallback:
        try:
            with _savepoint(conn, "valuation_csindex_fallback"):
                fallback_summary = _run_csindex_fallback(
                    conn,
                    set(valid_codes),
                    summary_as_of,
                    errors,
                    fetch=fallback_fetch or fetch_csindex_fallback,
                )
        except Exception as exc:  # noqa: BLE001 - fallback 失败不拖垮主链路
            errors.append(f"csindex_fallback: {exc}")

    # 收尾：全量刷新估值最新快照（ddl/80），供 /api/v1/valuation/indices 只读。
    latest_rows: Optional[int] = None
    if refresh_latest:
        try:
            with _savepoint(conn, "valuation_latest_snapshot"):
                latest_rows = refresh_valuation_latest(conn)
        except psycopg.errors.UndefinedTable:
            # 迁移 80 尚未应用的库（旧测试库/临时库）：跳过快照刷新，不影响主链路
            latest_rows = None
        except Exception as exc:  # noqa: BLE001
            errors.append(f"latest_snapshot: {exc}")

    # 全局数据新鲜度（be-data 的 bp_api.freshness / ddl/79）：从源表 MAX 推导写入。
    # 函数自身吞异常，ddl/79 未应用的库也会静默跳过，不影响主链路。
    try:
        from bp_api.freshness import sync_derived_freshness

        sync_derived_freshness(conn, ("index_valuation",))
    except Exception:  # noqa: BLE001
        pass

    summary = _summary(
        summary_as_of,
        indices,
        valuation_rows,
        series_rows,
        percentile_rows,
        errors,
        started_at,
    )
    summary["latest_rows"] = latest_rows
    summary["fallback"] = fallback_summary
    return summary
