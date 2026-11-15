# -*- coding: utf-8 -*-
"""本机全量回填 A 股日线（腾讯行情，bfq/qfq/hfq 三口径）→ 生产库 bp_stock_quote_daily。

用法（本机运行）：
    python scripts/local_backfill_stocks.py --years 6 --adjusts bfq,qfq,hfq --threads 8
    python scripts/local_backfill_stocks.py --limit 20          # 小样本验证
断点续跑：默认跳过已有数据的 (symbol, adjust)；--force 强制重抓。
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import threading
import time
from datetime import date, timedelta
from concurrent.futures import ThreadPoolExecutor, as_completed

import requests

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, REPO)
sys.stdout.reconfigure(encoding="utf-8")

import psycopg  # noqa: E402

TENCENT = "https://web.ifzq.gtimg.cn/appstock/app/fqkline/get"
UA = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/120.0 Safari/537.36"}
LOCK = threading.Lock()
PROGRESS = {"ok": 0, "failed": 0, "rows": 0}


def load_env() -> dict:
    values = {}
    env_path = os.path.join(REPO, ".env")
    if not os.path.exists(env_path):
        return values
    for line in open(env_path, encoding="utf-8"):
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        values[key.strip()] = value.strip().strip('"').strip("'")
    return values


def db_conn():
    env = load_env()
    host = os.getenv("BP_BACKFILL_DB_HOST") or "81.71.158.239"
    conninfo = (
        "host=" + host
        + " port=" + str(env.get("PGPORT", "5432"))
        + " dbname=" + env.get("PGDATABASE", "postgres")
        + " user=" + env.get("PGUSER", "postgres")
        + " password=" + env.get("PGPASSWORD", "")
    )
    conn = psycopg.connect(conninfo)
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


def fetch_chunk(session: requests.Session, symbol: str, start: date, end: date, adjust: str):
    """腾讯 kline：返回 [(date, open, high, low, close, volume)]。"""
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
    rows = data.get(key) or data.get("day") or []
    out = []
    for row in rows:
        if not isinstance(row, list) or len(row) < 6:
            continue
        try:
            trade_date = date.fromisoformat(str(row[0])[:10])
            open_, close_, high, low = float(row[1]), float(row[2]), float(row[3]), float(row[4])
            volume = int(float(row[5]))
        except (TypeError, ValueError):
            continue
        out.append((trade_date, open_, high, low, close_, volume))
    return out


def fetch_all(symbol: str, market: str, adjust: str, start_year: int, end: date):
    session = requests.Session()
    session.headers.update(UA)
    tx = tencent_symbol(symbol, market)
    rows = []
    cursor = date(start_year, 1, 1)
    while cursor < end:
        chunk_end = min(date(cursor.year + 2, 12, 31), end)
        rows.extend(fetch_chunk(session, tx, cursor, chunk_end, adjust))
        cursor = chunk_end + timedelta(days=1)
        time.sleep(0.02)
    # 去重（腾讯按块返回可能重叠首尾）
    dedup = {}
    for row in rows:
        dedup[row[0]] = row
    return [dedup[key] for key in sorted(dedup)]


def copy_rows(conn, symbol: str, adjust: str, rows, source="tencent_kline"):
    if not rows:
        return 0
    payload = []
    prev_close = None
    for trade_date, open_, high, low, close_, volume in rows:
        pct = None
        if prev_close and prev_close > 0:
            pct = (close_ / prev_close - 1.0) * 100.0
        prev_close = close_
        payload.append((symbol, trade_date, source, adjust, open_, high, low, close_, volume, pct))
    sql = (
        "INSERT INTO bp_stock_quote_daily"
        " (symbol, trade_date, source, adjust, open, high, low, close, volume, pct_change)"
        " VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)"
        " ON CONFLICT (symbol, trade_date, source, adjust) DO UPDATE SET"
        " open = EXCLUDED.open, high = EXCLUDED.high, low = EXCLUDED.low, close = EXCLUDED.close,"
        " volume = EXCLUDED.volume, pct_change = EXCLUDED.pct_change"
    )
    with conn.cursor() as cur:
        cur.executemany(sql, payload)
    conn.commit()
    return len(payload)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--years", type=int, default=6)
    parser.add_argument("--adjusts", type=str, default="bfq,qfq,hfq")
    parser.add_argument("--threads", type=int, default=8)
    parser.add_argument("--limit", type=int, default=0)
    parser.add_argument("--force", action="store_true")
    args = parser.parse_args()
    adjusts = [item.strip() for item in args.adjusts.split(",") if item.strip()]
    end = date.today()
    start_year = end.year - args.years

    with db_conn() as conn, conn.cursor() as cur:
        cur.execute("SELECT stock_code, market FROM bp_stock_master WHERE stock_code ~ '^[0-9]{6}$' ORDER BY stock_code")
        universe = [(row[0], row[1]) for row in cur.fetchall()]
        if not args.force:
            cur.execute("SELECT DISTINCT symbol || ':' || adjust FROM bp_stock_quote_daily")
            done = {row[0] for row in cur.fetchall()}
        else:
            done = set()
    if args.limit:
        universe = universe[: args.limit]
    targets = [(code, market, adjust) for code, market in universe for adjust in adjusts if f"{code}:{adjust}" not in done]
    print(f"universe={len(universe)} targets={len(targets)} adjusts={adjusts} years={args.years}", flush=True)

    def worker(code: str, market: str, adjust: str):
        try:
            rows = fetch_all(code, market, adjust, start_year, end)
            if not rows:
                raise RuntimeError("empty")
            with db_conn() as conn:
                written = copy_rows(conn, code, adjust, rows)
            with LOCK:
                PROGRESS["ok"] += 1
                PROGRESS["rows"] += written
                total = PROGRESS["ok"] + PROGRESS["failed"]
                if total % 50 == 0:
                    print(f"progress {total}/{len(targets)} ok={PROGRESS['ok']} fail={PROGRESS['failed']} rows={PROGRESS['rows']}", flush=True)
        except Exception as exc:  # noqa: BLE001
            with LOCK:
                PROGRESS["failed"] += 1
                print(f"fail {code} {adjust} {type(exc).__name__} {str(exc)[:80]}", flush=True)

    started = time.time()
    with ThreadPoolExecutor(max_workers=args.threads) as pool:
        futures = [pool.submit(worker, code, market, adjust) for code, market, adjust in targets]
        for future in as_completed(futures):
            future.result()
    print(f"done ok={PROGRESS['ok']} failed={PROGRESS['failed']} rows={PROGRESS['rows']} elapsed={int(time.time()-started)}s", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
