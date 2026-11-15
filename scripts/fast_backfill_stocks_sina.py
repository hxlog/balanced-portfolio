# -*- coding: utf-8 -*-
"""服务器侧快速 A 股回填（新浪原始行情 + hfq/qfq 因子，3 请求/只）。

bbfq = 原始价；hfq = 原始价 × hfq 因子；qfq = 原始价 ÷ qfq 因子（与 akshare 口径一致）。

用法（服务器）：
  python scripts/fast_backfill_stocks_sina.py --years 6 --threads 12
断点续跑：跳过已有全部三口径数据的 symbol。
"""
from __future__ import annotations

import argparse
import os
import re
import sys
import threading
import time
from bisect import bisect_right
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import date, datetime, timedelta
from datetime import timezone

import psycopg
import requests

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, REPO)
sys.stdout.reconfigure(encoding="utf-8")

UA = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/120.0 Safari/537.36", "Referer": "https://finance.sina.com.cn/"}
RAW = "https://money.finance.sina.com.cn/quotes_service/api/json_v2.php/CN_MarketData.getKLineData"
FACTOR = "https://finance.sina.com.cn/realstock/company/{symbol}/{kind}.js"
CN = timezone(timedelta(hours=8))
LOCK = threading.Lock()
PROGRESS = {"ok": 0, "failed": 0, "rows": 0}
local = threading.local()


def load_env() -> dict:
    values = {}
    path = os.path.join(REPO, ".env")
    if not os.path.exists(path):
        return values
    for line in open(path, encoding="utf-8"):
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        values[key.strip()] = value.split(" #")[0].strip().strip('"').strip("'")
    return values


def db_conn():
    env = load_env()
    conn = psycopg.connect(
        host=os.getenv("BP_BACKFILL_DB_HOST") or "81.71.158.239",
        port=int(env.get("PGPORT", "5432")),
        dbname=env.get("PGDATABASE", "postgres"),
        user=env.get("PGUSER", "postgres"),
        password=env.get("PGPASSWORD", ""),
    )
    with conn.cursor() as cur:
        cur.execute("SET synchronous_commit = off")
    conn.commit()
    return conn


def thread_conn():
    conn = getattr(local, "conn", None)
    if conn is None or conn.closed:
        conn = db_conn()
        local.conn = conn
        local.pending = 0
    return conn


def sina_symbol(code: str, market: str) -> str:
    market = (market or "").upper()
    if market == "SH":
        return "sh" + code
    if market == "SZ":
        return "sz" + code
    if market == "BJ":
        return "bj" + code
    return ("sh" if code.startswith(("6", "9")) else "sz") + code


def fetch_raw(session: requests.Session, symbol: str):
    response = session.get(RAW, params={"symbol": symbol, "scale": 240, "ma": "no", "datalen": 4000}, timeout=25)
    response.raise_for_status()
    rows = response.json()
    out = []
    for row in rows:
        try:
            day = date.fromisoformat(str(row["day"])[:10])
            out.append((day, float(row["open"]), float(row["high"]), float(row["low"]),
                        float(row["close"]), int(float(row["volume"]))))
        except (KeyError, TypeError, ValueError):
            continue
    return out


def fetch_factors(session: requests.Session, symbol: str, kind: str):
    response = session.get(FACTOR.format(symbol=symbol, kind=kind), timeout=25)
    if response.status_code != 200:
        return []
    pairs = re.findall(r'\{"d":"(\d{4}-\d{2}-\d{2})", *"f":"([0-9.]+)"\}', response.text)
    factors = sorted((date.fromisoformat(d), float(f)) for d, f in pairs)
    return factors


def factor_at(factors, day: date) -> float:
    if not factors:
        return 1.0
    dates = [item[0] for item in factors]
    idx = bisect_right(dates, day) - 1
    if idx < 0:
        return factors[0][1]
    return factors[idx][1]


INSERT_SQL = (
    "INSERT INTO bp_stock_quote_daily"
    " (symbol, trade_date, source, adjust, open, high, low, close, volume, pct_change)"
    " VALUES (%s, %s, 'sina_kline', %s, %s, %s, %s, %s, %s, %s)"
    " ON CONFLICT (symbol, trade_date, source, adjust) DO UPDATE SET"
    " open=EXCLUDED.open, high=EXCLUDED.high, low=EXCLUDED.low, close=EXCLUDED.close,"
    " volume=EXCLUDED.volume, pct_change=EXCLUDED.pct_change"
)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--years", type=int, default=6)
    parser.add_argument("--threads", type=int, default=12)
    parser.add_argument("--limit", type=int, default=0)
    args = parser.parse_args()
    cutoff = date.today() - timedelta(days=365 * args.years + 10)

    with db_conn() as conn, conn.cursor() as cur:
        cur.execute("SELECT stock_code, market FROM bp_stock_master WHERE stock_code ~ '^[0-9]{6}$' ORDER BY stock_code")
        universe = [(r[0], r[1]) for r in cur.fetchall()]
        cur.execute(
            "SELECT symbol FROM bp_stock_quote_daily WHERE adjust='bfq'"
            " AND symbol IN (SELECT symbol FROM bp_stock_quote_daily WHERE adjust='qfq')"
            " AND symbol IN (SELECT symbol FROM bp_stock_quote_daily WHERE adjust='hfq')"
        )
        done = {row[0] for row in cur.fetchall()}
    targets = [(code, market) for code, market in universe if code not in done]
    if args.limit:
        targets = targets[: args.limit]
    print(f"universe={len(universe)} targets={len(targets)} years={args.years}", flush=True)

    def worker(code: str, market: str):
        session = requests.Session()
        session.headers.update(UA)
        symbol = sina_symbol(code, market)
        try:
            raw = [row for row in fetch_raw(session, symbol) if row[0] >= cutoff]
            if not raw:
                raise RuntimeError("empty raw")
            hfq = fetch_factors(session, symbol, "hfq")
            qfq = fetch_factors(session, symbol, "qfq")
            series = {"bfq": [], "hfq": [], "qfq": []}
            for (day, open_, high, low, close_, volume) in raw:
                hf = factor_at(hfq, day)
                qf = factor_at(qfq, day) or 1.0
                series["bfq"].append((day, open_, high, low, close_, volume))
                series["hfq"].append((day, open_ * hf, high * hf, low * hf, close_ * hf, volume))
                series["qfq"].append((day, open_ / qf, high / qf, low / qf, close_ / qf, volume))
            payload = []
            for adjust, rows in series.items():
                previous = None
                for (day, open_, high, low, close_, volume) in rows:
                    pct = (close_ / previous - 1.0) * 100.0 if previous and previous > 0 else None
                    previous = close_
                    payload.append((code, day, adjust, round(open_, 4), round(high, 4), round(low, 4),
                                    round(close_, 4), volume, pct))
            conn = thread_conn()
            with conn.cursor() as cur:
                cur.executemany(INSERT_SQL, payload)
            local.pending = getattr(local, "pending", 0) + 1
            if local.pending >= 20:
                conn.commit()
                local.pending = 0
            with LOCK:
                PROGRESS["ok"] += 1
                PROGRESS["rows"] += len(payload)
                total = PROGRESS["ok"] + PROGRESS["failed"]
                if total % 200 == 0:
                    print(f"progress {total}/{len(targets)} ok={PROGRESS['ok']} fail={PROGRESS['failed']} rows={PROGRESS['rows']}", flush=True)
        except Exception as exc:  # noqa: BLE001
            with LOCK:
                PROGRESS["failed"] += 1
                if PROGRESS["failed"] % 50 == 1:
                    print(f"fail {code} {type(exc).__name__} {str(exc)[:60]}", flush=True)
        time.sleep(0.02)

    started = time.time()
    with ThreadPoolExecutor(max_workers=args.threads) as pool:
        futures = [pool.submit(worker, *target) for target in targets]
        for future in as_completed(futures):
            future.result()
    print(f"done ok={PROGRESS['ok']} failed={PROGRESS['failed']} rows={PROGRESS['rows']} elapsed={int(time.time()-started)}s", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
