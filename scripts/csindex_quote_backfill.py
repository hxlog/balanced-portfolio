"""中证官网行情回填：为东财不可达（或只在中证官网发布）的指数补齐日线。

数据源：https://www.csindex.com.cn/csindex-home/perf/index-perf
  - 返回 OHLC / changePct / tradingVol / tradingValue，2017 至今完整
  - 服务器可达（东财被封期间这仍是可用源）

写库口径：source = csindex_perf，adjust = bfq，category = index；
页面读行情只按 (symbol, adjust)，因此无需改动 API。
"""
import os
import random
import re
import sys
import time
from datetime import date

sys.path.insert(0, "/opt/balanced-portfolio")

import requests

from bp_ingest.config import load_config, setup_logging
from bp_ingest.db import QuoteRow, connect, upsert_quotes
from bp_ingest.http_session import install_hardened_session

API = "https://www.csindex.com.cn/csindex-home/perf/index-perf"
HOME = "https://www.csindex.com.cn/"
BUDGET_SECONDS = int(os.getenv("BP_CS_BUDGET", "600"))  # 单次预算（秒）
SLOW_DELAY = float(os.getenv("BP_CS_DELAY", "0.4"))  # 每只成功后的间隔（秒）
SOURCE = "csindex_perf"
# 平安口径里的供应商私有代码（东财/中证官网都没有对应指数），直接跳过
SKIP_RE = re.compile(r"^\d+L$|^FI|^SG|^DC|^CZ|^CICS|^INESC|^XI\d")
START = "20170101"
CHUNK_ROWS = 500


def warmup() -> None:
    """先访问一次官网首页，拿到 WAF 下发的 cookie，再调 JSON 接口。"""
    try:
        requests.get(HOME, timeout=20, headers={"User-Agent": "Mozilla/5.0 Chrome/120.0.0.0 Safari/537.36"})
    except Exception:  # noqa: BLE001
        pass


def fetch(symbol: str, end: str) -> list[dict]:
    response = requests.get(
        API,
        params={"indexCode": symbol, "startDate": START, "endDate": end},
        timeout=25,
        headers={
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
            "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
            "Referer": "https://www.csindex.com.cn/",
            "Accept": "application/json, text/plain, */*",
        },
    )
    response.raise_for_status()
    payload = response.json()
    return payload.get("data") or []


def to_rows(symbol: str, name: str, items: list[dict]) -> list[QuoteRow]:
    rows: list[QuoteRow] = []
    prev_close = None
    for item in items:
        try:
            trade_date = date(
                int(str(item["tradeDate"])[0:4]),
                int(str(item["tradeDate"])[4:6]),
                int(str(item["tradeDate"])[6:8]),
            )
        except Exception:  # noqa: BLE001
            continue
        close = item.get("close")
        if close is None:
            continue
        change_pct = item.get("changePct")
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
                pct_change=change_pct,
                adjust="bfq",
            ),
        )
        prev_close = close
    return rows


def main() -> int:
    setup_logging()
    install_hardened_session()
    warmup()
    app = load_config()
    end = date.today().strftime("%Y%m%d")
    with connect(app.db) as conn, conn.cursor() as cur:
        cur.execute(
            "select symbol from bp_index_config"
            " where is_deleted = 0 and category = %s and index_code is not null"
            " order by symbol",
            ("index",),
        )
        symbols = [row[0] for row in cur.fetchall()]
        cur.execute("select distinct symbol from bp_index_quote_daily where adjust = %s", ("bfq",))
        have = {row[0] for row in cur.fetchall()}
    missing = [symbol for symbol in symbols if symbol not in have and not SKIP_RE.search(symbol)]
    print("index symbols:", len(symbols), "missing:", len(missing), flush=True)

    ok = 0
    skipped = 0
    forbidden_streak = 0
    started = time.time()
    for index, symbol in enumerate(missing):
        if time.time() - started > BUDGET_SECONDS:
            print("budget exhausted", flush=True)
            break
        try:
            items = fetch(symbol, end)
            forbidden_streak = 0
        except Exception as exc:  # noqa: BLE001 - 兼容 curl_cffi / requests 两种 HTTPError
            status = getattr(getattr(exc, "response", None), "status_code", None)
            if status == 403:
                # 403 有两种可能：全局 WAF 拦 IP，或该代码在官网不存在（返回拦截页）。
                # 用控制代码 000300 探测：能通说明是「代码无效」，直接跳过。
                control_ok = False
                try:
                    control_ok = bool(fetch("000300", end))
                except Exception:  # noqa: BLE001
                    control_ok = False
                if control_ok:
                    print("skip-invalid", symbol, flush=True)
                    skipped += 1
                    time.sleep(0.4)
                    continue
                forbidden_streak += 1
                print("WAF 403", symbol, "streak", forbidden_streak, flush=True)
                if forbidden_streak >= 6:
                    print("WAF 连续 403，提前退出", flush=True)
                    break
                # 单次 403 可能只是瞬时限流：等 2 分钟后重试同一只
                time.sleep(120)
                continue
            print("fetch fail", symbol, type(exc).__name__, status, flush=True)
            time.sleep(0.8)
            continue

        if not items:
            skipped += 1
            time.sleep(0.1)
            continue
        name = items[0].get("indexNameCn") or symbol
        rows = to_rows(symbol, name, items)
        with connect(app.db) as conn:
            conn.autocommit = False
            for start in range(0, len(rows), CHUNK_ROWS):
                upsert_quotes(conn, rows[start : start + CHUNK_ROWS])
            conn.commit()
        ok += 1
        if (index + 1) % 20 == 0:
            print("progress %d/%d ok=%d skip=%d elapsed=%.0fs" % (
                index + 1, len(missing), ok, skipped, time.time() - started), flush=True)
        time.sleep(SLOW_DELAY + random.uniform(0, 0.3))
    print("done ok=%d skipped=%d elapsed=%.0fs" % (ok, skipped, time.time() - started), flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
