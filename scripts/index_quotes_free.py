#!/usr/bin/env python3
"""指数行情免费源多源降级采集（P0-3）：腾讯 ifzq -> 新浪 -> 中证官网 csindex -> 东财。

背景
----
旧指数行情 cron 停用 + bp_etl legacy 链受东财封 IP 影响后，跟踪指数当日行情
覆盖率从 674 只/日掉到 181 只/日。本脚本只负责 bp_index_master 中 is_tracked
的指数（A 股 / 中证 / 港股指数，不含个股/ETF），按免费源降级抓日线，
写入 bp_index_quote_daily（source 记录实际来源、adjust 记录复权口径）。

免费源优先级（免费源优先、失败换源、禁止伪造休市日数据）
--------------------------------------------------------
* A 股 / 中证指数：cn_index_tx（腾讯 fqkline）-> cn_index_sina（新浪日 K）
  -> csindex_perf（中证官网 index-perf，930/931/932/H3/950 等中证系唯一可用源）
  -> cn_index_em（东财 push2his，服务器 IP 长期封禁，仅最后手段）
* 港股指数：hk_index_tx（腾讯 hkfqkline）-> hk_index_em（东财）
* 非 CSI/SH/SZ/HK 市场（US/GLOBAL）：免费源不可用，跳过并在统计中单列。

写入口径
--------
* 冲突键必须含 symbol, source, adjust, trade_date（53 号迁移后的主键）；
  本脚本 adjust 固定 bfq（指数不复权，与 bp_etl legacy 链一致）；
* 当日行按 A 股收盘确认 15:10（CST，可用 BP_CLOSE_CONFIRM_HHMM 覆盖）
  过滤：盘中/收盘确认前不会把「今天」当成正式收盘写入；
* pct_change 优先用同一批次前收，缺失时回退库内该 symbol 最近收盘。

用法
----
    python scripts/index_quotes_free.py                     # 增量：全部跟踪指数，补到最新确认日
    python scripts/index_quotes_free.py --symbols 000300 930641
    python scripts/index_quotes_free.py --date 2026-11-27
    python scripts/index_quotes_free.py --source cn_index_tx csindex_perf
    python scripts/index_quotes_free.py --start 2026-10-01  # 指定抓取起始日（回填）
    python scripts/index_quotes_free.py --dry-run --json

退出码：0=执行完成（允许部分指数不可达）；1=无法确定目标交易日。
"""

from __future__ import annotations

import argparse
import json
import logging
import os
import random
import sys
import time
from contextlib import ExitStack
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta, timezone
from typing import Any, Callable, Iterable, Mapping, Optional, Sequence
from zoneinfo import ZoneInfo

logger = logging.getLogger("index_quotes_free")

# 直接执行 python scripts/index_quotes_free.py 时 sys.path[0] 是 scripts/，
# 补上仓库根目录以便 import bp_ingest / bp_etl（cron 从任意 cwd 启动都能跑）。
_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)

CN = ZoneInfo("Asia/Shanghai")

#: A 股收盘确认（15:10）后才认当日日 K；与 bp_ingest.calendar 口径一致。
DEFAULT_CLOSE_CONFIRM_HHMM = "1510"
DEFAULT_LOOKBACK_DAYS = 45
#: 读「各 symbol 最新日期」时的日期窗口（天）：避免对 700+ 标的/多年的行情大表
#: 做全表 GROUP BY（max(trade_date)）；窗口外的老数据按「无数据」处理并回看补齐。
DEFAULT_LAST_DATE_WINDOW_DAYS = 400
#: 腾讯 fqkline 单页条数（回填更长时向前翻页）。
TENCENT_PAGE_SIZE = 640

#: 市场 -> 免费源降级链（顺序即优先级；实际使用时再按 bp_data_source 注册情况过滤）。
SOURCE_CHAINS: dict[str, tuple[str, ...]] = {
    "A": ("cn_index_tx", "cn_index_sina", "csindex_perf", "cn_index_em"),
    "HK": ("hk_index_tx", "hk_index_em"),
}

#: 可以抓的指数市场（bp_index_master.market）。
SUPPORTED_MARKETS = ("CSI", "SH", "SZ", "HK")

TENCENT_KLINE_URL = "https://ifzq.gtimg.cn/appstock/app/fqkline/get"
TENCENT_HK_KLINE_URL = "https://web.ifzq.gtimg.cn/appstock/app/hkfqkline/get"
SINA_KLINE_URL = (
    "https://money.finance.sina.com.cn/quotes_service/api/json_v2.php/"
    "CN_MarketData.getKLineData"
)
CSINDEX_URL = "https://www.csindex.com.cn/csindex-home/perf/index-perf"
EM_KLINE_URL = "https://push2his.eastmoney.com/api/qt/stock/kline/get"
HTTP_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
    ),
    "Referer": "https://www.csindex.com.cn/",
    "Accept": "application/json, text/plain, */*",
}


class SourceError(RuntimeError):
    """单个免费源取数失败（连接/反爬/空响应），由降级链换源。"""


@dataclass(frozen=True)
class IndexMeta:
    symbol: str
    market: str
    name: str = ""

    @property
    def market_group(self) -> str:
        return "HK" if self.market == "HK" else "A"


@dataclass
class SymbolOutcome:
    symbol: str
    market: str
    status: str  # covered / partial / missing / skipped
    source: str | None = None
    latest_date: date | None = None
    rows: int = 0
    attempts: list[dict[str, Any]] = field(default_factory=list)


# ---------------------------------------------------------------------------
# 时间口径
# ---------------------------------------------------------------------------
def now_cn(now: datetime | None = None) -> datetime:
    """当前（或给定）时刻的 CST 时间；naive 视为已是 CST。"""
    if now is None:
        return datetime.now(CN)
    if now.tzinfo is None:
        return now.replace(tzinfo=CN)
    return now.astimezone(CN)


def close_confirm_time() -> tuple[int, int]:
    raw = (os.getenv("BP_CLOSE_CONFIRM_HHMM") or DEFAULT_CLOSE_CONFIRM_HHMM).strip()
    if len(raw) == 4 and raw.isdigit():
        return int(raw[:2]), int(raw[2:])
    return 15, 10


def is_close_confirmed(trade_date: date, now: datetime) -> bool:
    """该交易日日 K 是否已可作为正式收盘（等价 bp_ingest.calendar 的口径）。"""
    wall = now_cn(now)
    if trade_date < wall.date():
        return True
    if trade_date > wall.date():
        return False
    hour, minute = close_confirm_time()
    return wall.timetz().replace(tzinfo=None) >= datetime.min.time().replace(
        hour=hour, minute=minute
    )


def resolve_target_date(conn: Any, now: datetime | None = None) -> date | None:
    """目标交易日：最近已收盘确认的 A 股交易日（DB 交易日历）。"""
    wall = now_cn(now)
    cutoff = wall.date()
    with conn.cursor() as cur:
        cur.execute(
            "SELECT max(cal_date) FROM bp_trading_calendar"
            " WHERE market = 'CN' AND is_trading AND cal_date <= %s",
            (cutoff,),
        )
        row = cur.fetchone()
    candidate = row[0] if row else None
    if candidate is None:
        return None
    if candidate == cutoff and not is_close_confirmed(candidate, wall):
        with conn.cursor() as cur:
            cur.execute(
                "SELECT max(cal_date) FROM bp_trading_calendar"
                " WHERE market = 'CN' AND is_trading AND cal_date < %s",
                (candidate,),
            )
            row = cur.fetchone()
        return row[0] if row else None
    return candidate


# ---------------------------------------------------------------------------
# 行情解析（纯函数，便于单测）
# ---------------------------------------------------------------------------
def _num(value: Any) -> Optional[float]:
    try:
        if value is None or value == "":
            return None
        return float(value)
    except (TypeError, ValueError):
        return None


def _bar(
    trade_date: date,
    open_: Any,
    high: Any,
    low: Any,
    close: Any,
    volume: Any = None,
    amount: Any = None,
) -> Optional[dict[str, Any]]:
    close_value = _num(close)
    if close_value is None or close_value <= 0:
        return None
    open_value = _num(open_)
    high_value = _num(high)
    low_value = _num(low)
    # 防御脏行：OHLC 关系明显错误（源反爬返回占位/错列）直接丢弃，不写脏数据
    for value in (open_value, high_value, low_value):
        if value is not None and value <= 0:
            return None
    if high_value is not None and low_value is not None and high_value < low_value:
        return None
    volume_value = _num(volume)
    return {
        "trade_date": trade_date,
        "open": open_value,
        "high": high_value,
        "low": low_value,
        "close": close_value,
        "volume": int(volume_value) if volume_value is not None else None,
        "amount": _num(amount),
    }


def parse_tencent_kline(payload: Mapping[str, Any], code: str) -> list[dict[str, Any]]:
    """腾讯 fqkline 日线：data[code].day = [date, open, close, high, low, volume, ...]。"""
    node = (payload.get("data") or {}).get(code)
    if not isinstance(node, dict):
        return []
    arr = node.get("day") or node.get("hfqday") or node.get("qfqday") or []
    bars: list[dict[str, Any]] = []
    for item in arr:
        if not isinstance(item, (list, tuple)) or len(item) < 6:
            continue
        try:
            day = date.fromisoformat(str(item[0]))
        except (TypeError, ValueError):
            continue
        bar = _bar(day, item[1], item[3], item[4], item[2], item[5])
        if bar is not None:
            bars.append(bar)
    return bars


def parse_tencent_hk_kline(payload: Mapping[str, Any], code: str) -> list[dict[str, Any]]:
    """腾讯 hkfqkline 日线：data[code].day 结构同 A 股（open, close, high, low, volume）。"""
    return parse_tencent_kline(payload, code)


def parse_sina_kline(payload: Any) -> list[dict[str, Any]]:
    """新浪日 K：[{day, open, high, low, close, volume}, ...]（按时间升序）。"""
    if not isinstance(payload, list):
        return []
    bars: list[dict[str, Any]] = []
    for item in payload:
        if not isinstance(item, dict):
            continue
        try:
            day = date.fromisoformat(str(item.get("day")))
        except (TypeError, ValueError):
            continue
        bar = _bar(day, item.get("open"), item.get("high"), item.get("low"),
                   item.get("close"), item.get("volume"))
        if bar is not None:
            bars.append(bar)
    return bars


def parse_csindex_perf(payload: Mapping[str, Any]) -> list[dict[str, Any]]:
    """中证官网 index-perf：data = [{tradeDate: YYYYMMDD, open/high/low/close, tradingVol/tradingValue}]。"""
    rows = payload.get("data") if isinstance(payload, Mapping) else None
    if not isinstance(rows, list):
        return []
    bars: list[dict[str, Any]] = []
    for item in rows:
        if not isinstance(item, dict):
            continue
        raw = str(item.get("tradeDate") or "")
        if len(raw) != 8 or not raw.isdigit():
            continue
        try:
            day = date(int(raw[:4]), int(raw[4:6]), int(raw[6:8]))
        except ValueError:
            continue
        bar = _bar(day, item.get("open"), item.get("high"), item.get("low"),
                   item.get("close"), item.get("tradingVol"), item.get("tradingValue"))
        if bar is not None:
            bars.append(bar)
    return bars


def parse_em_kline(payload: Mapping[str, Any]) -> list[dict[str, Any]]:
    """东财 push2his：data.klines = [date,open,close,high,low,volume,amount,amplitude]。"""
    data = payload.get("data") if isinstance(payload, Mapping) else None
    rows = (data or {}).get("klines") if isinstance(data, dict) else None
    if not isinstance(rows, list):
        return []
    bars: list[dict[str, Any]] = []
    for row in rows:
        parts = str(row).split(",")
        if len(parts) < 6:
            continue
        try:
            day = date.fromisoformat(parts[0])
        except (TypeError, ValueError):
            continue
        bar = _bar(day, parts[1], parts[3], parts[4], parts[2],
                   parts[5], parts[6] if len(parts) > 6 else None)
        if bar is not None:
            bars.append(bar)
    return bars


# ---------------------------------------------------------------------------
# 市场前缀 / 东财 secid
# ---------------------------------------------------------------------------
def market_prefixes(symbol: str, market: str) -> list[str]:
    """腾讯/新浪的带市场前缀代码候选（sh/sz）。中证系 930/931/932/H3/950 无前缀源。"""
    sym = (symbol or "").strip()
    if market == "SH":
        return [f"sh{sym}"]
    if market == "SZ":
        return [f"sz{sym}"]
    if market == "CSI":
        if sym.startswith(("399", "159")):
            return [f"sz{sym}"]
        if sym.startswith(("930", "931", "932", "950", "H3")):
            return []
        if sym.startswith(("000", "001", "002", "003", "880", "999")):
            return [f"sh{sym}"]
        return [f"sh{sym}", f"sz{sym}"]
    return []


def hk_tencent_code(symbol: str) -> str:
    return f"hk{symbol}"


def em_secid_candidates(symbol: str, market: str) -> list[str]:
    """东财 secid 候选：沪=1.，深=0.，中证系=2.，港股指数按 100/124/116 前缀探测。"""
    sym = (symbol or "").strip()
    if market == "SH":
        return [f"1.{sym}"]
    if market == "SZ":
        return [f"0.{sym}"]
    if market == "CSI":
        if sym.startswith(("399", "159")):
            return [f"0.{sym}"]
        if sym.startswith(("930", "931", "932", "950", "H3")):
            return [f"2.{sym}"]
        return [f"1.{sym}", f"2.{sym}"]
    if market == "HK":
        return [f"{prefix}.{sym}" for prefix in ("100", "124", "116")]
    return []


# ---------------------------------------------------------------------------
# 免费源取数（网络层；失败抛 SourceError，由降级链换源）
# ---------------------------------------------------------------------------
def _http_get_json(url: str, params: Mapping[str, Any], *, timeout: float = 20.0) -> Any:
    import requests  # noqa: PLC0415 - 延迟导入，单测可完全 mock 网络层

    try:
        response = requests.get(url, params=params, timeout=timeout, headers=HTTP_HEADERS)
        response.raise_for_status()
        return response.json()
    except Exception as exc:  # noqa: BLE001 - 统一归为源不可用，交给降级链
        raise SourceError(f"{type(exc).__name__}: {exc}") from exc


def fetch_tencent_a(symbol: str, market: str, start: date, end: date) -> list[dict[str, Any]]:
    """腾讯 ifzq fqkline（A 股/中证指数，指数恒为不复权口径）。"""
    codes = market_prefixes(symbol, market)
    if not codes:
        raise SourceError("no_tencent_prefix")
    code = codes[0]
    bars: list[dict[str, Any]] = []
    page_end = end
    for _ in range(40):
        param = f"{code},day,{start.isoformat()},{page_end.isoformat()},{TENCENT_PAGE_SIZE},"
        payload = _http_get_json(TENCENT_KLINE_URL, {"param": param})
        page = parse_tencent_kline(payload, code)
        if not page:
            break
        bars = page + bars
        earliest = min(bar["trade_date"] for bar in page)
        if earliest <= start or len(page) < TENCENT_PAGE_SIZE:
            break
        page_end = earliest - timedelta(days=1)
        if page_end < start:
            break
    return bars


def fetch_tencent_hk(symbol: str, market: str, start: date, end: date) -> list[dict[str, Any]]:
    """腾讯 hkfqkline（港股指数：hkHSI/hkHSTECH 等）。"""
    code = hk_tencent_code(symbol)
    param = f"{code},day,{start.isoformat()},{end.isoformat()},640,qfq"
    payload = _http_get_json(TENCENT_HK_KLINE_URL, {"param": param})
    return parse_tencent_hk_kline(payload, code)


def fetch_sina(symbol: str, market: str, start: date, end: date) -> list[dict[str, Any]]:
    """新浪日 K（A 股/指数，带 sh/sz 前缀；中证系 930+ 无数据则换源）。"""
    codes = market_prefixes(symbol, market)
    if not codes:
        raise SourceError("no_sina_prefix")
    code = codes[0]
    needed = max(1, (end - start).days + 10)
    params = {"symbol": code, "scale": "240", "ma": "no", "datalen": str(min(1023, needed))}
    payload = _http_get_json(SINA_KLINE_URL, params)
    if payload in (None, []):
        return []
    return parse_sina_kline(payload)


def fetch_csindex(symbol: str, market: str, start: date, end: date) -> list[dict[str, Any]]:
    """中证官网 index-perf（930/931/932/H3/950 等中证系指数的官方日线）。"""
    params = {
        "indexCode": symbol,
        "startDate": start.strftime("%Y%m%d"),
        "endDate": end.strftime("%Y%m%d"),
    }
    payload = _http_get_json(CSINDEX_URL, params)
    return parse_csindex_perf(payload)


def fetch_eastmoney(symbol: str, market: str, start: date, end: date) -> list[dict[str, Any]]:
    """东财 push2his（最后手段；服务器 IP 长期封禁，只在其它免费源全挂时使用）。"""
    secids = em_secid_candidates(symbol, market)
    if not secids:
        raise SourceError("no_em_secid")
    last_error: Exception | None = None
    for secid in secids:
        params = {
            "secid": secid,
            "fields1": "f1,f2,f3,f4,f5,f6",
            "fields2": "f51,f52,f53,f54,f55,f56,f57,f58",
            "klt": "101",
            "fqt": "0",
            "beg": start.strftime("%Y%m%d"),
            "end": end.strftime("%Y%m%d"),
        }
        try:
            payload = _http_get_json(EM_KLINE_URL, params)
        except SourceError as exc:
            last_error = exc
            continue
        bars = parse_em_kline(payload)
        if bars:
            return bars
    if last_error is not None:
        raise last_error
    return []


FETCHERS: dict[str, Callable[[str, str, date, date], list[dict[str, Any]]]] = {
    "cn_index_tx": fetch_tencent_a,
    "hk_index_tx": fetch_tencent_hk,
    "cn_index_sina": fetch_sina,
    "csindex_perf": fetch_csindex,
    "cn_index_em": fetch_eastmoney,
    "hk_index_em": fetch_eastmoney,
}


# ---------------------------------------------------------------------------
# 数据库读（可 monkeypatch，便于纯 mock 单测）
# ---------------------------------------------------------------------------
def load_registered_sources(conn: Any) -> set[str]:
    try:
        with conn.cursor() as cur:
            cur.execute("SELECT code FROM bp_data_source")
            return {row[0] for row in cur.fetchall()}
    except Exception:  # noqa: BLE001 - 迁移未应用/连接异常时不阻断，按 FETCHERS 全量
        return set(FETCHERS)


def load_universe(
    conn: Any,
    *,
    symbols: Optional[Iterable[str]] = None,
    include_hk: bool = True,
    markets: Optional[Sequence[str]] = None,
) -> list[IndexMeta]:
    """bp_index_master 中 is_tracked 的指数（默认含港股指数）。"""
    sql = (
        "SELECT index_code, market, coalesce(name, '') FROM bp_index_master"
        " WHERE is_tracked = TRUE"
    )
    params: list[Any] = []
    if markets:
        wanted_markets = [item for item in markets if item in SUPPORTED_MARKETS]
    else:
        wanted_markets = list(SUPPORTED_MARKETS) if include_hk else ["CSI", "SH", "SZ"]
    markets = wanted_markets or (["CSI", "SH", "SZ"] if not include_hk else list(SUPPORTED_MARKETS))
    sql += " AND market = ANY(%s)"
    params.append(markets)
    wanted = [str(item).strip() for item in (symbols or []) if str(item).strip()]
    if wanted:
        sql += " AND index_code = ANY(%s)"
        params.append(wanted)
    sql += " ORDER BY market, index_code"
    with conn.cursor() as cur:
        cur.execute(sql, params)
        rows = cur.fetchall()
    return [IndexMeta(symbol=row[0], market=row[1], name=row[2] or "") for row in rows]


def load_last_dates(
    conn: Any,
    adjust: str,
    *,
    reference: Optional[date] = None,
    window_days: int = DEFAULT_LAST_DATE_WINDOW_DAYS,
) -> dict[str, date]:
    """各 symbol 最新行情日；**限定日期窗口**（避免全表 max/GROUP BY 扫描）。"""
    reference = reference or date.today()
    since = reference - timedelta(days=max(1, int(window_days)))
    with conn.cursor() as cur:
        cur.execute(
            "SELECT symbol, max(trade_date) FROM bp_index_quote_daily"
            " WHERE adjust = %s AND trade_date >= %s GROUP BY symbol",
            (adjust, since),
        )
        return {row[0]: row[1] for row in cur.fetchall() if row[1] is not None}


def previous_close(conn: Any, symbol: str, adjust: str, before: date) -> Optional[float]:
    with conn.cursor() as cur:
        cur.execute(
            "SELECT close FROM bp_index_quote_daily"
            " WHERE symbol = %s AND adjust = %s AND trade_date < %s"
            " ORDER BY trade_date DESC LIMIT 1",
            (symbol, adjust, before),
        )
        row = cur.fetchone()
    return float(row[0]) if row and row[0] is not None else None


def count_covered(conn: Any, symbols: Sequence[str], trade_date: date, adjust: str) -> int:
    if not symbols:
        return 0
    with conn.cursor() as cur:
        cur.execute(
            "SELECT count(DISTINCT symbol) FROM bp_index_quote_daily"
            " WHERE trade_date = %s AND adjust = %s AND symbol = ANY(%s)",
            (trade_date, adjust, list(symbols)),
        )
        row = cur.fetchone()
    return int(row[0]) if row and row[0] is not None else 0


def write_rows(conn: Any, rows: Sequence[Any]) -> int:
    from bp_ingest.db import upsert_quotes  # noqa: PLC0415 - 惰性导入，纯 mock 单测不触发

    written = upsert_quotes(conn, rows)
    conn.commit()
    return written


# ---------------------------------------------------------------------------
# 核心流程
# ---------------------------------------------------------------------------
def _to_quote_rows(
    meta: IndexMeta,
    bars: Sequence[dict[str, Any]],
    *,
    source: str,
    adjust: str,
    start: date,
    target: date,
    prev_close: Optional[float],
) -> list[Any]:
    """把解析后的 bar 转成 QuoteRow：窗口过滤 + 去重 + pct_change 补全。"""
    from bp_ingest.db import QuoteRow  # noqa: PLC0415

    ordered = sorted(
        (bar for bar in bars if start <= bar["trade_date"] <= target),
        key=lambda item: item["trade_date"],
    )
    seen: dict[date, dict[str, Any]] = {}
    for bar in ordered:
        seen[bar["trade_date"]] = bar
    rows: list[Any] = []
    previous = prev_close
    for day in sorted(seen):
        bar = seen[day]
        pct = None
        if previous is not None and previous > 0:
            pct = (bar["close"] / previous - 1.0) * 100.0
        rows.append(
            QuoteRow(
                trade_date=day,
                symbol=meta.symbol,
                source=source,
                category="index",
                name=meta.name or meta.symbol,
                open=bar["open"],
                high=bar["high"],
                low=bar["low"],
                close=bar["close"],
                volume=bar["volume"],
                amount=bar["amount"],
                turnover_rate=None,
                pct_change=pct,
                adjust=adjust,
            )
        )
        previous = bar["close"]
    return rows


def _source_chain(
    meta: IndexMeta,
    registered: set[str],
    source_filter: Optional[Sequence[str]],
) -> list[str]:
    chain = [name for name in SOURCE_CHAINS[meta.market_group] if name in registered]
    if source_filter:
        wanted = {str(item).strip() for item in source_filter if str(item).strip()}
        chain = [name for name in chain if name in wanted]
    return chain


def _report(text: str, payload: Mapping[str, Any]) -> None:
    print(text.format(**payload))


def run(
    app: Any = None,
    *,
    symbols: Optional[Sequence[str]] = None,
    target_date: Optional[date] = None,
    start_date: Optional[date] = None,
    source_filter: Optional[Sequence[str]] = None,
    include_hk: bool = True,
    markets: Optional[Sequence[str]] = None,
    lookback_days: int = DEFAULT_LOOKBACK_DAYS,
    dry_run: bool = False,
    limit: Optional[int] = None,
    conn_factory: Optional[Callable[[], Any]] = None,
    fetchers: Optional[Mapping[str, Callable]] = None,
    writer: Optional[Callable[[Any, Sequence[Any]], int]] = None,
    now: Optional[datetime] = None,
    sleep_seconds: float = 0.15,
) -> dict[str, Any]:
    """执行一轮指数行情免费源采集，返回覆盖统计。"""
    wall = now_cn(now)
    fetch_map = dict(fetchers or FETCHERS)
    write = writer or write_rows
    with ExitStack() as stack:
        if conn_factory is not None:
            conn = conn_factory()
        else:
            if app is None:
                from bp_ingest.config import load_config  # noqa: PLC0415

                app = load_config()
            from bp_ingest.db import connect  # noqa: PLC0415

            conn = stack.enter_context(connect(app.db))
        target = target_date or resolve_target_date(conn, wall)
        if target is None:
            return {"status": "no_trade_date", "target_date": None}
        # P2：显式 --date=today（或任何未确认的当日目标）必须强制收盘确认，
        # 盘中/收盘确认前不抓不写，避免把实时快照当成当日日 K 入库。
        if target > wall.date():
            return {
                "status": "invalid_target_date",
                "target_date": target.isoformat(),
                "generated_at": wall.isoformat(),
            }
        if target == wall.date() and not is_close_confirmed(target, wall):
            return {
                "status": "not_closed",
                "target_date": target.isoformat(),
                "generated_at": wall.isoformat(),
                "reason": "before_close_confirm",
            }
        universe = load_universe(
            conn, symbols=symbols, include_hk=include_hk, markets=markets
        )
        if limit:
            universe = universe[: max(1, int(limit))]
        registered = load_registered_sources(conn)
        last_dates = load_last_dates(conn, "bfq", reference=target)
        symbols_all = [meta.symbol for meta in universe]
        already = sum(
            1
            for meta in universe
            if last_dates.get(meta.symbol) and last_dates[meta.symbol] >= target
        )

        outcomes: list[SymbolOutcome] = []
        by_source: dict[str, int] = {}
        failure_reasons: dict[str, int] = {}
        total_rows = 0
        for index, meta in enumerate(universe):
            last = last_dates.get(meta.symbol)
            if last is not None and last >= target:
                outcomes.append(
                    SymbolOutcome(meta.symbol, meta.market, "skipped", latest_date=last)
                )
                continue
            start = start_date or (
                (last + timedelta(days=1)) if last else (target - timedelta(days=lookback_days))
            )
            if start > target:
                outcomes.append(
                    SymbolOutcome(meta.symbol, meta.market, "skipped", latest_date=last)
                )
                continue
            chain = _source_chain(meta, registered, source_filter)
            outcome = SymbolOutcome(meta.symbol, meta.market, "missing")
            prev = previous_close(conn, meta.symbol, "bfq", start)
            for source in chain:
                fetcher = fetch_map.get(source)
                if fetcher is None:
                    outcome.attempts.append({"source": source, "status": "no_fetcher"})
                    failure_reasons["no_fetcher"] = failure_reasons.get("no_fetcher", 0) + 1
                    continue
                try:
                    bars = fetcher(meta.symbol, meta.market, start, target)
                except Exception as exc:  # noqa: BLE001 - 单源失败换下一个
                    reason = type(exc).__name__
                    outcome.attempts.append(
                        {"source": source, "status": "error", "reason": str(exc)[:120]}
                    )
                    failure_reasons[reason] = failure_reasons.get(reason, 0) + 1
                    continue
                rows = _to_quote_rows(
                    meta, bars, source=source, adjust="bfq",
                    start=start, target=target, prev_close=prev,
                )
                if not rows:
                    outcome.attempts.append({"source": source, "status": "empty"})
                    failure_reasons["empty"] = failure_reasons.get("empty", 0) + 1
                    continue
                latest = rows[-1].trade_date
                outcome.source = source
                outcome.latest_date = latest
                outcome.rows = len(rows)
                by_source[source] = by_source.get(source, 0) + 1
                if not dry_run:
                    try:
                        total_rows += int(write(conn, rows) or 0)
                    except Exception as exc:  # noqa: BLE001 - 写失败不中断整轮
                        outcome.attempts.append(
                            {"source": source, "status": "write_error",
                             "reason": type(exc).__name__}
                        )
                        failure_reasons["write_error"] = failure_reasons.get("write_error", 0) + 1
                        outcome.source = None
                        continue
                outcome.status = "covered" if latest >= target else "partial"
                if outcome.status == "covered":
                    break
            outcomes.append(outcome)
            if sleep_seconds > 0:
                time.sleep(sleep_seconds * (0.8 + random.random() * 0.4))
            if (index + 1) % 100 == 0:
                logger.info("index_quotes_free 进度 %d/%d", index + 1, len(universe))

        covered = sum(1 for item in outcomes if item.status == "covered")
        partial = sum(1 for item in outcomes if item.status == "partial")
        missing = [
            item.symbol for item in outcomes if item.status in ("missing", "partial")
        ]
        skipped = sum(1 for item in outcomes if item.status == "skipped")
        if dry_run:
            db_covered = (covered + already) if universe else 0
        else:
            db_covered = count_covered(conn, symbols_all, target, "bfq")
        covered_ratio = (db_covered / len(universe)) if universe else 0.0

        payload = {
            "status": "ok" if covered_ratio >= 0.99 else "partial",
            "target_date": target.isoformat(),
            "dry_run": dry_run,
            "universe": len(universe),
            "already_covered": already,
            "covered": covered,
            "partial": partial,
            "skipped": skipped,
            "db_covered": db_covered,
            "coverage": round(covered_ratio, 4),
            "rows_written": total_rows,
            "by_source": by_source,
            "failure_reasons": failure_reasons,
            "missing": missing[:200],
            "missing_total": len(missing),
            "generated_at": wall.isoformat(),
        }
        if not dry_run and universe:
            _record_freshness(target, payload)
        return payload


def _record_freshness(target: date, payload: Mapping[str, Any]) -> None:
    """收尾写入全局新鲜度（index_quotes 类）；失败不影响采集结果。"""
    try:
        from bp_api.freshness import record_freshness_standalone  # noqa: PLC0415

        ratio = float(payload.get("coverage") or 0.0)
        status = "ok" if ratio >= 0.99 else ("lagging" if ratio >= 0.5 else "stale")
        record_freshness_standalone(
            "index_quotes",
            target,
            status=status,
            source="scripts/index_quotes_free.py",
            meta={
                "universe": payload.get("universe"),
                "covered": payload.get("db_covered"),
                "coverage": ratio,
                "by_source": payload.get("by_source"),
            },
        )
    except Exception:  # noqa: BLE001
        logger.warning("写入 index_quotes 数据新鲜度失败（不影响采集）", exc_info=True)


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------
def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="index_quotes_free.py",
        description="跟踪指数行情免费源多源降级采集（腾讯->新浪->中证官网->东财）",
    )
    parser.add_argument("--symbols", nargs="+", default=None,
                        help="仅处理指定指数代码（空格分隔，默认全部 is_tracked）")
    parser.add_argument("--date", dest="date", default=None,
                        help="目标交易日 YYYY-MM-DD（默认最近已收盘确认的 A 股交易日）")
    parser.add_argument("--start", dest="start", default=None,
                        help="抓取起始日 YYYY-MM-DD（默认按库内该 symbol 最新日期+1；无数据则回看 lookback 天）")
    parser.add_argument("--source", nargs="+", default=None,
                        help="限定使用哪些源（cn_index_tx cn_index_sina csindex_perf cn_index_em hk_index_tx hk_index_em）")
    parser.add_argument("--markets", default="CSI,SH,SZ,HK",
                        help="指数市场过滤，逗号分隔（默认 CSI,SH,SZ,HK）")
    parser.add_argument("--lookback-days", type=int, default=DEFAULT_LOOKBACK_DAYS,
                        help=f"无历史数据的 symbol 默认回看天数（默认 {DEFAULT_LOOKBACK_DAYS}）")
    parser.add_argument("--limit", type=int, default=0, help="仅处理前 N 只（冒烟）")
    parser.add_argument("--dry-run", action="store_true", help="只抓取与统计，不写库")
    parser.add_argument("--json", action="store_true", help="以 JSON 输出统计")
    parser.add_argument("--log-level", default="INFO")
    return parser


def _parse_date_arg(raw: Optional[str], argument: str) -> Optional[date]:
    if raw is None or not str(raw).strip():
        return None
    try:
        return date.fromisoformat(str(raw).strip())
    except ValueError as exc:
        raise SystemExit(f"{argument} 需为 YYYY-MM-DD: {raw}") from exc


def main(argv: Optional[Sequence[str]] = None) -> int:
    args = build_parser().parse_args(argv)
    logging.basicConfig(
        level=getattr(logging, str(args.log_level).upper(), logging.INFO),
        format="%(asctime)s | %(levelname)-7s | %(name)s | %(message)s",
    )
    try:
        from bp_ingest.config import load_config, setup_logging  # noqa: PLC0415
        from bp_ingest.http_session import install_hardened_session  # noqa: PLC0415

        setup_logging(getattr(load_config(), "log_level", "INFO"))
        install_hardened_session()
    except Exception:  # noqa: BLE001 - 安装硬化会话失败降级为普通 requests
        logger.warning("硬化会话安装失败，降级为 requests", exc_info=True)

    markets = [item.strip().upper() for item in str(args.markets).split(",") if item.strip()]
    unsupported = [item for item in markets if item not in SUPPORTED_MARKETS]
    if unsupported:
        logger.warning("免费源不支持的市场已跳过: %s", ",".join(unsupported))
    include_hk = "HK" in markets

    payload = run(
        symbols=args.symbols,
        target_date=_parse_date_arg(args.date, "--date"),
        start_date=_parse_date_arg(args.start, "--start"),
        source_filter=args.source,
        include_hk=include_hk,
        markets=markets,
        lookback_days=args.lookback_days,
        dry_run=args.dry_run,
        limit=args.limit or None,
    )
    if args.json:
        print(json.dumps(payload, ensure_ascii=False, default=str, indent=1))
    elif payload.get("status") == "no_trade_date":
        print("无法确定目标交易日（交易日历为空）")
    elif payload.get("status") == "not_closed":
        print("目标交易日未过收盘确认（--date=today 盘中），本轮不抓不写")
    elif payload.get("status") == "invalid_target_date":
        print("目标交易日非法（未来日期），本轮不抓不写")
    else:
        print(
            "target={target_date} universe={universe} covered={db_covered} "
            "({coverage:.2%}) already={already_covered} rows={rows_written} "
            "sources={by_source} missing={missing_total}".format(**payload)
        )
        if payload.get("missing"):
            print("missing sample:", " ".join(payload["missing"][:20]))
    if payload.get("status") in ("no_trade_date", "invalid_target_date"):
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
