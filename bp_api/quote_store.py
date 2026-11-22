"""代码解析与多市场行情读取（只读）。

统一 /api/v1/market/* 的「代码 → 行情表」解析，避免每个端点各写一套：

- A 股 / 港股：bp_stock_quote_daily（港股 symbol 为 5 位码）
- 场内基金（ETF/LOF/封闭式）：bp_etf_quote_daily
- 指数：bp_index_quote_daily

解析优先级：stock > etf > index（同名代码如 000001 会命中平安银行而非上证指数；
需要指数时显式加 IDX: 前缀，或使用不会被股票占用的指数代码）。显式前缀：
STK: / ETF: / IDX:。

本模块只做读取，不计算指标、不写库。
"""
from __future__ import annotations

import re
from datetime import date
from typing import Any, Iterable, Optional

import psycopg

KIND_STOCK = "stock"
KIND_ETF = "etf"
KIND_INDEX = "index"
KINDS = (KIND_STOCK, KIND_ETF, KIND_INDEX)

_CODE_RE = re.compile(r"^(?:(SH|SZ|BJ|HK)[.:]?)?(\d{5,6})(?:\.(SH|SZ|BJ|HK))?$", re.I)
_FORCED_RE = re.compile(r"^(STK|ETF|IDX)[:.](.+)$", re.I)
_FORCED_KIND = {"STK": KIND_STOCK, "ETF": KIND_ETF, "IDX": KIND_INDEX}
_MARKET_BY_PREFIX = {"SH": "SH", "SZ": "SZ", "BJ": "BJ", "HK": "HK"}


def _market_from_code(code: str) -> str:
    """按代码前缀猜交易所（仅用于展示；实际以主数据/表内存在性为准）。"""
    if len(code) == 5:
        return "HK"
    head = code[0]
    if head in ("6", "9"):
        return "SH"
    if head == "5":
        return "SH"          # 上交所 ETF
    if head == "1":
        return "SZ"          # 深交所 ETF/LOF
    if head in ("4", "8"):
        return "BJ"
    return "SZ"


def normalize_code(raw: str) -> Optional[tuple[str, str, Optional[str]]]:
    """把用户输入规范化成 (code, market_guess, forced_kind)；非法返回 None。

    支持：601318 / 601318.SH / sh601318 / HK02020 / 02020.HK /
    STK:601318 / ETF:159915 / IDX:000300。
    """
    text = (raw or "").strip().upper().replace(" ", "")
    if not text:
        return None
    forced: Optional[str] = None
    forced_match = _FORCED_RE.match(text)
    if forced_match:
        forced = _FORCED_KIND[forced_match.group(1)]
        text = forced_match.group(2)
    match = _CODE_RE.match(text)
    if not match:
        return None
    prefix, code, suffix = match.groups()
    if len(code) == 5:
        market = "HK"
    else:
        hint = (suffix or prefix or "").upper()
        market = _MARKET_BY_PREFIX.get(hint) or _market_from_code(code)
    return code, market, forced


def _names(conn: psycopg.Connection, codes: list[str]) -> dict[str, dict[str, tuple[str, str]]]:
    """返回 {kind: {code: (name, market)}}。"""
    out: dict[str, dict[str, tuple[str, str]]] = {kind: {} for kind in KINDS}
    if not codes:
        return out
    with conn.cursor() as cur:
        cur.execute(
            "SELECT stock_code, name, market FROM bp_stock_master WHERE stock_code = ANY(%s)",
            (codes,),
        )
        for code, name, market in cur.fetchall():
            out[KIND_STOCK][code] = (name or "", market or "")
        cur.execute(
            "SELECT etf_code, name, market FROM bp_etf_master WHERE etf_code = ANY(%s)",
            (codes,),
        )
        for code, name, market in cur.fetchall():
            out[KIND_ETF][code] = (name or "", market or "")
        cur.execute(
            "SELECT index_code, name, market FROM bp_index_master WHERE index_code = ANY(%s)",
            (codes,),
        )
        for code, name, market in cur.fetchall():
            out[KIND_INDEX][code] = (name or "", market or "")
    return out


def _present(conn: psycopg.Connection, table: str, column: str, codes: list[str], adjust: str) -> set[str]:
    if not codes:
        return set()
    with conn.cursor() as cur:
        cur.execute(
            f"SELECT DISTINCT {column} FROM {table} WHERE {column} = ANY(%s) AND adjust = %s",
            (codes, adjust),
        )
        return {row[0] for row in cur.fetchall()}


def resolve_codes(
    conn: psycopg.Connection, raw_codes: Iterable[str], adjust: str = "bfq"
) -> tuple[dict[str, dict[str, Any]], list[str]]:
    """解析代码 → 资产信息。

    返回 (resolved, invalid)：resolved 的 key 是原始输入，value 为
    {code, market, currency, kind, name, canonical}。
    """
    resolved: dict[str, dict[str, Any]] = {}
    invalid: list[str] = []
    parsed: list[tuple[str, str, str, Optional[str]]] = []
    for raw in raw_codes:
        normalized = normalize_code(raw)
        if normalized is None:
            invalid.append(raw)
            continue
        code, market, forced = normalized
        parsed.append((raw, code, market, forced))
    if not parsed:
        return resolved, invalid
    bare = list(dict.fromkeys(code for _, code, _, _ in parsed))
    names = _names(conn, bare)
    present: dict[str, set[str]] = {}
    for kind, table, column in (
        (KIND_STOCK, "bp_stock_quote_daily", "symbol"),
        (KIND_ETF, "bp_etf_quote_daily", "etf_code"),
    ):
        # 表可能尚未迁移（旧库），缺失时按「无数据」处理，避免端点整体 500。
        try:
            present[kind] = _present(conn, table, column, bare, adjust)
        except psycopg.errors.UndefinedTable:  # pragma: no cover - 旧库兼容
            conn.rollback()
            present[kind] = set()
    if adjust == "bfq":
        present[KIND_INDEX] = _present(conn, "bp_index_quote_daily", "symbol", bare, adjust)
    else:
        present[KIND_INDEX] = set()

    for raw, code, market, forced in parsed:
        candidates = [forced] if forced else [KIND_STOCK, KIND_ETF, KIND_INDEX]
        chosen = None
        for kind in candidates:
            if kind is None:
                continue
            if code in present.get(kind, set()) or (forced and code in names.get(kind, {})):
                chosen = kind
                break
        if chosen is None:
            # 没有行情也没有强制类型：只要主数据里唯一命中，就返回 unknown 行（带名称）。
            known = [kind for kind in candidates if kind and code in names.get(kind, {})]
            if len(known) == 1:
                chosen = known[0]
        if chosen is None:
            invalid.append(raw)
            continue
        name, master_market = names.get(chosen, {}).get(code, ("", ""))
        effective_market = (master_market or market).upper() or market
        resolved[raw] = {
            "code": code,
            "kind": chosen,
            "market": effective_market,
            "currency": "HKD" if effective_market == "HK" else "CNY",
            "name": name,
            "canonical": f"{code}.{effective_market}",
        }
    return resolved, invalid


_LATEST_SQL = {
    KIND_STOCK: (
        "SELECT DISTINCT ON (symbol) symbol, trade_date, close, source, adjust"
        " FROM bp_stock_quote_daily WHERE symbol = ANY(%s) AND adjust = %s"
        " ORDER BY symbol, trade_date DESC, source"
    ),
    KIND_ETF: (
        "SELECT DISTINCT ON (etf_code) etf_code, trade_date, close, source, adjust"
        " FROM bp_etf_quote_daily WHERE etf_code = ANY(%s) AND adjust = %s"
        " ORDER BY etf_code, trade_date DESC, source"
    ),
    KIND_INDEX: (
        "SELECT DISTINCT ON (symbol) symbol, trade_date, close, source, adjust"
        " FROM bp_index_quote_daily WHERE symbol = ANY(%s) AND adjust = %s"
        " ORDER BY symbol, trade_date DESC, source"
    ),
}

_PREV_SQL = {
    KIND_STOCK: (
        "SELECT trade_date, close FROM bp_stock_quote_daily WHERE symbol = %s AND adjust = %s"
        " AND trade_date < %s ORDER BY trade_date DESC LIMIT 1"
    ),
    KIND_ETF: (
        "SELECT trade_date, close FROM bp_etf_quote_daily WHERE etf_code = %s AND adjust = %s"
        " AND trade_date < %s ORDER BY trade_date DESC LIMIT 1"
    ),
    KIND_INDEX: (
        "SELECT trade_date, close FROM bp_index_quote_daily WHERE symbol = %s AND adjust = %s"
        " AND trade_date < %s ORDER BY trade_date DESC LIMIT 1"
    ),
}


def latest_rows(
    conn: psycopg.Connection,
    resolved: dict[str, dict[str, Any]],
    adjust: str = "bfq",
) -> dict[str, dict[str, Any]]:
    """按原始输入 key 返回每个代码的最新一条日线（含前收）。"""
    grouped: dict[str, list[str]] = {}
    for info in resolved.values():
        grouped.setdefault(info["kind"], []).append(info["code"])
    rows: dict[str, dict[str, Any]] = {}
    for kind, codes in grouped.items():
        unique = list(dict.fromkeys(codes))
        with conn.cursor() as cur:
            cur.execute(_LATEST_SQL[kind], (unique, adjust))
            fetched = cur.fetchall()
        by_code: dict[str, dict[str, Any]] = {}
        for code, trade_date, close, source, adj in fetched:
            by_code[code] = {"date": trade_date, "close": close, "source": source, "adjust": adj}
        for code, row in by_code.items():
            with conn.cursor() as cur:
                cur.execute(_PREV_SQL[kind], (code, adjust, row["date"]))
                previous = cur.fetchone()
            row["prev_close"] = previous[1] if previous else None
            row["prev_date"] = previous[0] if previous else None
        for raw, info in resolved.items():
            if info["kind"] == kind and info["code"] in by_code:
                rows[raw] = by_code[info["code"]]
    return rows


_HISTORY_SQL = {
    KIND_STOCK: (
        "SELECT symbol, trade_date, open, high, low, close, volume, amount, pct_change, source, adjust"
        " FROM bp_stock_quote_daily WHERE symbol = ANY(%s) AND adjust = %s"
        " AND (%s::date IS NULL OR trade_date >= %s) AND (%s::date IS NULL OR trade_date <= %s)"
        " ORDER BY symbol, trade_date DESC LIMIT %s"
    ),
    KIND_ETF: (
        "SELECT etf_code, trade_date, open, high, low, close, volume, amount, pct_change, source, adjust"
        " FROM bp_etf_quote_daily WHERE etf_code = ANY(%s) AND adjust = %s"
        " AND (%s::date IS NULL OR trade_date >= %s) AND (%s::date IS NULL OR trade_date <= %s)"
        " ORDER BY etf_code, trade_date DESC LIMIT %s"
    ),
    KIND_INDEX: (
        "SELECT symbol, trade_date, open, high, low, close, volume, amount, pct_change, source, adjust"
        " FROM bp_index_quote_daily WHERE symbol = ANY(%s) AND adjust = %s"
        " AND (%s::date IS NULL OR trade_date >= %s) AND (%s::date IS NULL OR trade_date <= %s)"
        " ORDER BY symbol, trade_date DESC LIMIT %s"
    ),
}


def history_rows(
    conn: psycopg.Connection,
    resolved: dict[str, dict[str, Any]],
    *,
    adjust: str = "bfq",
    start: Optional[date] = None,
    end: Optional[date] = None,
    limit: int = 50_000,
) -> tuple[list[dict[str, Any]], bool]:
    """跨市场历史日线；返回 (rows, truncated)。行按 date 升序、code 升序。"""
    by_kind_code = {(info["kind"], info["code"]): info for info in resolved.values()}
    grouped: dict[str, list[str]] = {}
    for info in resolved.values():
        grouped.setdefault(info["kind"], []).append(info["code"])
    rows: list[dict[str, Any]] = []
    truncated = False
    for kind, codes in grouped.items():
        unique = list(dict.fromkeys(codes))
        with conn.cursor() as cur:
            cur.execute(_HISTORY_SQL[kind], (unique, adjust, start, start, end, end, limit + 1))
            fetched = cur.fetchall()
        if len(fetched) > limit:
            truncated = True
            fetched = fetched[:limit]
        for code, trade_date, open_, high, low, close, volume, amount, pct, source, adj in fetched:
            info = by_kind_code.get((kind, code))
            rows.append(
                {
                    "code": info["canonical"] if info else code,
                    "code_raw": code,
                    "kind": kind,
                    "market": info["market"] if info else "",
                    "currency": info["currency"] if info else "CNY",
                    "date": trade_date,
                    "open": open_,
                    "high": high,
                    "low": low,
                    "close": close,
                    "volume": volume,
                    "amount": amount,
                    "pct_change": pct,
                    "source": source,
                    "adjust": adj,
                }
            )
    # 同一 (code, date, adjust) 多源重复时按来源优先级保留一条：
    # 腾讯/中证/东财等主源优先，新浪（降级源）最后。避免 /market/history 返回重复行。
    def _source_rank(source: Any) -> int:
        text = str(source or "").lower()
        if text.startswith(("tencent", "csindex", "em_", "em")):
            return 0
        if text.startswith("sina"):
            return 2
        return 1

    deduped: dict[tuple[str, date, str], dict[str, Any]] = {}
    for row in rows:
        key = (row["code"], row["date"], str(row.get("adjust") or ""))
        current = deduped.get(key)
        if current is None or _source_rank(row.get("source")) < _source_rank(current.get("source")):
            deduped[key] = row
    rows = list(deduped.values())
    rows.sort(key=lambda row: (row["date"], row["code"]))
    return rows, truncated


def latest_trade_date(conn: psycopg.Connection) -> Optional[date]:
    """覆盖快照里的最新交易日（一次轻量查询，供 Excel 显示数据日期参考）。"""
    try:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT max(last_date) FROM bp_asset_coverage WHERE kind IN ('stock', 'etf', 'index')"
            )
            row = cur.fetchone()
    except psycopg.errors.UndefinedTable:  # pragma: no cover - 旧库兼容
        conn.rollback()
        return None
    return row[0] if row else None
