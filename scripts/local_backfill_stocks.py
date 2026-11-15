# -*- coding: utf-8 -*-
"""本机全量回填 A 股日线（腾讯行情，bfq/qfq/hfq 三口径）→ 生产库 bp_stock_quote_daily。

优化：每线程一个持久连接 + 跨股票批量提交（每 20 只 commit），大幅降低 WAN 往返。

用法：
    python scripts/local_backfill_stocks.py --years 6 --threads 12
    python scripts/local_backfill_stocks.py --limit 20
断点续跑：默认跳过已有数据的 (symbol, adjust)；--force 强制重抓。
"""
from __future__ import annotations

import argparse
import os
import sys
import threading
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import date, timedelta

import psycopg
import requests

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, REPO)
sys.stdout.reconfigure(encoding="utf-8")

TENCENT = "https://web.ifzq.gtimg.cn/appstock/app/fqkline/get"
UA = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/120.0 Safari/537.36"}
LOCK = threading.Lock()
PROGRESS = {"ok": 0, "failed": 0, "rows": 0}
BATCH_CODES = 20


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


def db_conn(host=None):
    env = load_env()
    conn = psycopg.connect(
        host=host or os.getenv("BP_BACKFILL_DB_HOST") or "81.71.158.239",
        port=int(env.get("PGPORT", "5432")),
        dbname=env.get("PGDATABASE", "postgres"),
        user=env.get("PGUSER", "postgres"),
        password=env.get("PGPASSWORD", ""),
    )
    with conn.cursor() as cur:
        cur.execute("SET synchronous_commit = off")
    conn.commit()
    return conn


def tencent_symbol(code: str, market: str) -> str:
    market = (market or "").upper()
    if market == "SH":
        return "sh" + code
    if market == "SZ":
        return "sz" + code
    if market == "BJ":
        return "bj" + code
    return ("sh" if code.startswith(("6", "9")) else "sz") + code


def fetch_chunk(session, symbol: str, start: date, end: date, adjust: str):
    kind = "" if adjust == "bfq" else adjust
    params = ",".join([symbol, "day", start.isoformat(), end.isoformat(), "640", kind])
    try:
        response = session.get(TENCENT, params={"param": params}, timeout=20)
        response.raise_for_status()
        payload = response.json()
    except Exception:
        return []
    data = (payload.get("data") or {}).get(symbol) or {}
    key = {"bfq": "day", "qfq": "qfqday", "hfq": "hfqday"}[adjust]
    out = []
    for row in data.get(key) or data.get("day") or []:
        if not isinstance(row, list) or len(row) < 6:
            continue
        try:
            out.append((date.fromisoformat(str(row[0])[:10]),
                        float(row[1]), float(row[3]), float(row[4]), float(row[2]), int(float(row[5]))))
        except (TypeError, ValueError):
            continue
    return out


def fetch_all(session, symbol: str, market: str, adjusts, start_year: int, end: date):
    tx = tencent_symbol(symbol, market)
    result = {}
    for adjust in adjusts:
        rows = []
        cursor = date(start_year, 1, 1)
        while cursor < end:
            chunk_end = min(date(cursor.year + 2, 12, 31), end)
            rows.extend(fetch_chunk(session, tx, cursor, chunk_end, adjust))
            cursor = chunk_end + timedelta(days=1)
            time.sleep(0.01)
        dedup = {row[0]: row for row in rows}
        result[adjust] = [dedup[key] for key in sorted(dedup)]
    return result


INSERT_SQL = (
    "INSERT INTO bp_stock_quote_daily"
    " (symbol, trade_date, source, adjust, open, high, low, close, volume, pct_change)"
    " VALUES (%s, %s, 'tencent_kline', %s, %s, %s, %s, %s, %s, %s)"
    " ON CONFLICT (symbol, trade_date, source, adjust) DO UPDATE SET"
    " open=EXCLUDED.open, high=EXCLUDED.high, low=EXCLUDED.low, close=EXCLUDED.close,"
    " volume=EXCLUDED.volume, pct_change=EXCLUDED.pct_change"
)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--years", type=int, default=6)
    parser.add_argument("--adjusts", type=str, default="bfq,qfq,hfq")
    parser.add_argument("--threads", type=int, default=12)
    parser.add_argument("--limit", type=int, default=0)
    parser.add_argument("--force", action="store_true")
    args = parser.parse_args()
    adjusts = [item.strip() for item in args.adjusts.split(",") if item.strip()]
    end = date.today()
    start_year = end.year - args.years

    with db_conn() as conn, conn.cursor() as cur:
        cur.execute("SELECT stock_code, market FROM bp_stock_master WHERE stock_code ~ '^[0-9]{6}$' ORDER BY stock_code")
        universe = [(row[0], row[1]) for row in cur.fetchall()]
        cur.execute("SELECT DISTINCT symbol || ':' || adjust FROM bp_stock_quote_daily")
        done = {row[0] for row in cur.fetchall()} if not args.force else set()
    if args.limit:
        universe = universe[: args.limit]
    targets = []
    for code, market in universe:
        missing = [a for a in adjusts if f"{code}:{a}" not in done]
        if missing:
            targets.append((code, market, missing))
    print(f"universe={len(universe)} codes={len(targets)} adjusts={adjusts} years={args.years}", flush=True)

    local = threading.local()

    def thread_conn():
        conn = getattr(local, "conn", None)
        if conn is None or conn.closed:
            conn = db_conn()
            local.conn = conn
            local.pending = 0
        return conn

    def flush(conn, force=False):
        local.pending = getattr(local, "pending", 0)
        if force or local.pending >= 20:
            conn.commit()
            local.pending = 0

    def worker(code: str, market: str, missing):
        session = requests.Session()
        session.headers.update(UA)
        try:
            data = fetch_all(session, code, market, missing, start_year, end)
            rows = []
            for adjust, series in data.items():
                previous = None
                for (trade_date, open_, high, low, close_, volume) in series:
                    pct = None
                    if previous and previous > 0:
                        pct = (close_ / previous - 1.0) * 100.0
                    previous = close_
                    rows.append((code, trade_date, adjust, open_, high, low, close_, volume, pct))
            if not rows:
                raise RuntimeError("empty")
            conn = thread_conn()
            with conn.cursor() as cur:
                cur.executemany(INSERT_SQL, rows)
            local.pending += 1
            flush(conn)
            with LOCK:
                PROGRESS["ok"] += 1
                PROGRESS["rows"] += len(rows)
                total = PROGRESS["ok"] + PROGRESS["failed"]
                if total % 100 == 0:
                    print(f"progress {total}/{len(targets)} ok={PROGRESS['ok']} fail={PROGRESS['failed']} rows={PROGRESS['rows']}", flush=True)
        except Exception as exc:  # noqa: BLE001
            with LOCK:
                PROGRESS["failed"] += 1
                if PROGRESS["failed"] % 20 == 1:
                    print(f"fail {code} {type(exc).__name__} {str(exc)[:60]}", flush=True)

    started = time.time()
    with ThreadPoolExecutor(max_workers=args.threads) as pool:
        futures = [pool.submit(worker, *target) for target in targets]
        for future in as_completed(futures):
            future.result()
    print(f"done ok={PROGRESS['ok']} failed={PROGRESS['failed']} rows={PROGRESS['rows']} elapsed={int(time.time()-started)}s", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
