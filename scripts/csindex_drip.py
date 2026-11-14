"""中证官网行情慢速补齐（drip）：小批量 + 长间隔，避免触发 WAF。

背景：中证官网 JSON API 对突发请求会立刻 403。实测：连续 3 次即封，但冷却后单个请求可通。
因此改为「每个 symbol 成功后再等 8~12s；遇 403 指数退避 60/120/240s 后重试」的慢速模式，
由 cron 每小时跑一次（每次预算 50 分钟），数小时内可补齐数百只。
"""
from __future__ import annotations

import random
import sys
import time
from datetime import date

sys.path.insert(0, "/opt/balanced-portfolio")

import requests

from bp_ingest.config import load_config, setup_logging
from bp_ingest.db import QuoteRow, connect, upsert_quotes
from bp_ingest.valuation_ingest import _build_macro_rows  # noqa: F401  (保持 import 兼容)
from bp_ingest.http_session import install_hardened_session

API = "https://www.csindex.com.cn/csindex-home/perf/index-perf"
HOME = "https://www.csindex.com.cn/"
SOURCE = "csindex_perf"
START = "20170101"
BUDGET_SECONDS = 3000
BASE_DELAY = (8.0, 12.0)
BACKOFF = (60, 120, 240)


def warmup() -> None:
    try:
        requests.get(HOME, timeout=20, headers={"User-Agent": "Mozilla/5.0 Chrome/120"})
    except Exception:  # noqa: BLE001
        pass


def fetch(symbol: str, end: str) -> list[dict]:
    response = requests.get(
        API,
        params={"indexCode": symbol, "startDate": START, "endDate": end},
        timeout=30,
        headers={
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
            "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
            "Referer": "https://www.csindex.com.cn/",
            "Accept": "application/json, text/plain, */*",
        },
    )
    response.raise_for_status()
    return (response.json().get("data") or [])


def to_rows(symbol: str, items: list[dict]) -> list[QuoteRow]:
    rows: list[QuoteRow] = []
    name = items[0].get("indexNameCn") if items else symbol
    for item in items:
        raw_date = str(item.get("tradeDate") or "")
        if len(raw_date) != 8:
            continue
        try:
            trade_date = date(int(raw_date[:4]), int(raw_date[4:6]), int(raw_date[6:8]))
        except Exception:  # noqa: BLE001
            continue
        close = item.get("close")
        if close is None:
            continue
        rows.append(
            QuoteRow(
                trade_date=trade_date,
                symbol=symbol,
                source=SOURCE,
                category="index",
                name=name,
                open=item.get("open"),
                high=item.get("high"),
                low=item.get("low"),
                close=close,
                volume=int(item["tradingVol"]) if item.get("tradingVol") else None,
                amount=item.get("tradingValue"),
                turnover_rate=None,
                pct_change=item.get("changePct"),
                adjust="bfq",
            ),
        )
    return rows


def main() -> int:
    setup_logging()
    install_hardened_session()
    warmup()
    app = load_config()
    end = date.today().strftime("%Y%m%d")
    with connect(app.db) as conn, conn.cursor() as cur:
        cur.execute("select symbol from bp_index_config where is_deleted = 0 and category = %s and index_code is not null order by symbol", ("index",))
        symbols = [row[0] for row in cur.fetchall()]
        cur.execute("select distinct symbol from bp_index_quote_daily where adjust = %s", ("bfq",))
        have = {row[0] for row in cur.fetchall()}
    missing = [symbol for symbol in symbols if symbol not in have]
    print("missing:", len(missing), flush=True)

    started = time.time()
    ok = 0
    skipped = 0
    banned = 0
    for symbol in missing:
        if time.time() - started > BUDGET_SECONDS:
            print("budget exhausted", flush=True)
            break
        attempt = 0
        items = None
        while attempt <= len(BACKOFF):
            try:
                items = fetch(symbol, end)
                banned = 0
                break
            except Exception as exc:  # noqa: BLE001
                status = getattr(getattr(exc, "response", None), "status_code", None)
                if status == 403 and attempt < len(BACKOFF):
                    wait = BACKOFF[attempt]
                    banned += 1
                    print("403 backoff", wait, "s for", symbol, flush=True)
                    time.sleep(wait)
                    attempt += 1
                    continue
                print("fetch fail", symbol, type(exc).__name__, status, flush=True)
                items = None
                break
        if not items:
            skipped += 1
            time.sleep(3)
            continue
        rows = to_rows(symbol, items)
        if not rows:
            skipped += 1
            time.sleep(2)
            continue
        with connect(app.db) as conn:
            conn.autocommit = False
            for start in range(0, len(rows), 500):
                upsert_quotes(conn, rows[start : start + 500])
            conn.commit()
        ok += 1
        print("ok %s rows=%d ok_total=%d skip=%d elapsed=%.0fs" % (symbol, len(rows), ok, skipped, time.time() - started), flush=True)
        if banned:
            time.sleep(30)
        else:
            time.sleep(random.uniform(*BASE_DELAY))
    print("done ok=%d skipped=%d elapsed=%.0fs" % (ok, skipped, time.time() - started), flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
