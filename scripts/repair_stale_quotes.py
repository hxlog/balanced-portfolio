"""修复滞后的指数行情（用户追问的 191/33/15 只缺口）。

通道优先级：
1) 新浪/腾讯（000/399 等 A 股指数，快）；
2) 中证官网 index-perf（CSI 系 930/H3 等，经 SG relay）；
3) 反向兜底：CS 失败再试新浪/腾讯。
"""
from __future__ import annotations

import os
import sys
import time
from datetime import date, datetime, timedelta, timezone

sys.path.insert(0, "/opt/balanced-portfolio")
sys.stdout.reconfigure(encoding="utf-8")

import pandas as pd
import requests

from bp_api.repositories_valuation import upsert_quote_health
from bp_ingest.config import load_config, setup_logging
from bp_ingest.db import QuoteRow, connect, upsert_quotes
from bp_ingest.http_session import install_hardened_session
from bp_ingest.sources import _fetch_cn_index_sina, _fetch_cn_index_tx

CS_API = "https://www.csindex.com.cn/csindex-home/perf/index-perf"
CS_PROXY = "http://127.0.0.1:10809"
CS_HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/120.0 Safari/537.36",
    "Referer": "https://www.csindex.com.cn/",
    "Accept": "application/json, text/plain, */*",
}
BUDGET_SECONDS = int(os.getenv("BP_REPAIR_BUDGET", "2400"))


def _rows_from_frame(symbol: str, frame: pd.DataFrame, source: str) -> list[QuoteRow]:
    if frame is None or frame.empty:
        return []
    rows: list[QuoteRow] = []
    frame = frame.copy()
    frame["trade_date"] = pd.to_datetime(frame["trade_date"]).dt.date
    for _, item in frame.iterrows():
        close = item.get("close")
        if close is None or pd.isna(close):
            continue
        rows.append(
            QuoteRow(
                trade_date=item["trade_date"],
                symbol=symbol,
                source=source,
                category="index",
                name=symbol,
                open=None if pd.isna(item.get("open")) else float(item["open"]),
                high=None if pd.isna(item.get("high")) else float(item["high"]),
                low=None if pd.isna(item.get("low")) else float(item["low"]),
                close=float(close),
                volume=None if pd.isna(item.get("volume")) else int(item["volume"]),
                amount=None if pd.isna(item.get("amount")) else float(item["amount"]),
                turnover_rate=None if pd.isna(item.get("turnover_rate")) else float(item["turnover_rate"]),
                pct_change=None if pd.isna(item.get("pct_change")) else float(item["pct_change"]),
                adjust="bfq",
            )
        )
    return rows


def fetch_sina(symbol: str, start: date, end: date) -> list[QuoteRow]:
    try:
        frame = _fetch_cn_index_sina(symbol, start, end, {})
        return _rows_from_frame(symbol, frame, "cn_index_sina")
    except Exception:  # noqa: BLE001
        return []


def fetch_tx(symbol: str, start: date, end: date) -> list[QuoteRow]:
    try:
        frame = _fetch_cn_index_tx(symbol, start, end, {})
        return _rows_from_frame(symbol, frame, "cn_index_tx")
    except Exception:  # noqa: BLE001
        return []


_CS_SESSION: requests.Session | None = None
_CS_PROXY_SESSION: requests.Session | None = None


def _cs_session() -> requests.Session:
    global _CS_SESSION
    if _CS_SESSION is None:
        _CS_SESSION = requests.Session()
        _CS_SESSION.headers.update(CS_HEADERS)
    return _CS_SESSION


def _cs_proxy_session() -> requests.Session:
    global _CS_PROXY_SESSION
    if _CS_PROXY_SESSION is None:
        _CS_PROXY_SESSION = requests.Session()
        _CS_PROXY_SESSION.proxies = {"http": CS_PROXY, "https": CS_PROXY}
        _CS_PROXY_SESSION.headers.update(CS_HEADERS)
    return _CS_PROXY_SESSION


def _cs_request(session: requests.Session, symbol: str, start: date, end: date, timeout: int = 12):
    return session.get(
        CS_API,
        params={
            "indexCode": symbol,
            "startDate": start.strftime("%Y%m%d"),
            "endDate": end.strftime("%Y%m%d"),
        },
        timeout=timeout,
    )


def _parse_cs_payload(payload: dict, symbol: str) -> list[QuoteRow]:
    rows: list[QuoteRow] = []
    for item in payload.get("data") or []:
        raw_date = str(item.get("tradeDate") or "")
        if len(raw_date) != 8:
            continue
        close = item.get("close")
        if close is None:
            continue
        try:
            trade_date = date(int(raw_date[:4]), int(raw_date[4:6]), int(raw_date[6:8]))
        except ValueError:
            continue
        rows.append(
            QuoteRow(
                trade_date=trade_date,
                symbol=symbol,
                source="csindex_perf",
                category="index",
                name=item.get("indexNameCn") or symbol,
                open=item.get("open"),
                high=item.get("high"),
                low=item.get("low"),
                close=close,
                volume=int(item["tradingVol"]) if item.get("tradingVol") else None,
                amount=item.get("tradingValue"),
                turnover_rate=None,
                pct_change=item.get("changePct"),
                adjust="bfq",
            )
        )
    return rows


def fetch_csindex(symbol: str, start: date, end: date) -> list[QuoteRow]:
    """中证官网 index-perf：直连优先，403/WAF 时经 SG relay 兜底（relay ~2s/只）。"""
    attempts = ((_cs_session(), 12), (_cs_proxy_session(), 60))
    for session, timeout in attempts:
        try:
            response = _cs_request(session, symbol, start, end, timeout=timeout)
        except Exception:  # noqa: BLE001
            continue
        if response.status_code != 200:
            continue
        try:
            payload = response.json()
        except Exception:  # noqa: BLE001
            continue
        rows = _parse_cs_payload(payload, symbol)
        if rows:
            return rows
    return []


SINA_API = "https://money.finance.sina.com.cn/quotes_service/api/json_v2.php/CN_MarketData.getKLineData"


def sina_symbol(symbol: str) -> str | None:
    """A 股指数代码 → 新浪 symbol（000xx=sh, 399xx=sz）。"""
    if len(symbol) != 6 or not symbol.isdigit():
        return None
    if symbol.startswith("000"):
        return "sh" + symbol
    if symbol.startswith("399"):
        return "sz" + symbol
    return None


def fetch_sina_direct(symbol: str, end: date) -> list[QuoteRow]:
    """新浪 K 线直连（快，~0.15s/只），覆盖 000/399 系 A 股指数。"""
    sina = sina_symbol(symbol)
    if not sina:
        return []
    try:
        response = requests.get(
            SINA_API,
            params={"symbol": sina, "scale": "240", "ma": "no", "datalen": "60"},
            headers={"User-Agent": CS_HEADERS["User-Agent"], "Referer": "https://finance.sina.com.cn/"},
            timeout=15,
        )
        if response.status_code != 200:
            return []
        payload = response.json()
    except Exception:  # noqa: BLE001
        return []
    if not isinstance(payload, list):
        return []
    rows: list[QuoteRow] = []
    prev_close = None
    for item in payload:
        raw_date = str(item.get("day") or "")
        if len(raw_date) < 10:
            continue
        try:
            trade_date = date(int(raw_date[:4]), int(raw_date[5:7]), int(raw_date[8:10]))
        except ValueError:
            continue
        try:
            close = float(item.get("close"))
        except (TypeError, ValueError):
            continue
        pct = None
        if prev_close:
            pct = (close / prev_close - 1) * 100
        rows.append(
            QuoteRow(
                trade_date=trade_date,
                symbol=symbol,
                source="cn_index_sina",
                category="index",
                name=symbol,
                open=float(item["open"]) if item.get("open") else None,
                high=float(item["high"]) if item.get("high") else None,
                low=float(item["low"]) if item.get("low") else None,
                close=close,
                volume=int(float(item["volume"])) if item.get("volume") else None,
                amount=None,
                turnover_rate=None,
                pct_change=pct,
                adjust="bfq",
            )
        )
        prev_close = close
    return rows


def prefer_ashare(symbol: str) -> bool:
    if not symbol[:1].isdigit():
        return False
    if symbol[:2] in ("93", "95", "97", "98"):
        return False
    return True


def repair_symbol(symbol: str, last: date | None, today: date) -> list[QuoteRow]:
    start = (last - timedelta(days=10)) if last else (today - timedelta(days=400))
    if prefer_ashare(symbol):
        rows = fetch_sina_direct(symbol, today)
        if not rows:
            rows = fetch_sina(symbol, start, today)
        if not rows:
            rows = fetch_csindex(symbol, start, today)
        return rows
    rows = fetch_csindex(symbol, start, today)
    if not rows:
        rows = fetch_sina(symbol, start, today) or fetch_tx(symbol, start, today)
    return rows


def main() -> int:
    setup_logging()
    install_hardened_session()
    app = load_config()
    today = date.today()
    with connect(app.db) as conn, conn.cursor() as cur:
        cur.execute(
            "SELECT h.symbol, h.last_trade_date, h.lag_trading_days FROM bp_index_quote_health h"
            " WHERE h.status IN ('stale', 'dead') ORDER BY h.lag_trading_days DESC",
        )
        targets = cur.fetchall()
    print("repair targets:", len(targets), flush=True)
    started = time.time()
    ok = 0
    failed = 0
    for symbol, last, lag in targets:
        if time.time() - started > BUDGET_SECONDS:
            print("budget exhausted", flush=True)
            break
        rows = repair_symbol(symbol, last, today)
        if not rows:
            failed += 1
            continue
        try:
            with connect(app.db) as conn:
                conn.autocommit = False
                upsert_quotes(conn, rows)
                conn.commit()
            ok += 1
            print("fixed", symbol, "lag", lag, "rows", len(rows), flush=True)
        except Exception as exc:  # noqa: BLE001
            failed += 1
            print("write fail", symbol, type(exc).__name__, str(exc)[:100], flush=True)
        time.sleep(0.3)
    print("repair done ok=%d failed=%d elapsed=%.0fs" % (ok, failed, time.time() - started), flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
