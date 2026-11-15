# -*- coding: utf-8 -*-
"""A 股日增量 ETL（服务器运行）：腾讯批量快照 → bp_stock_quote_daily.bfq。

--mode daily   批量快照（1 请求/60 只，全市场约 90 请求，1~2 分钟），仅收盘确认后写入当日 bfq；
--mode weekly  近 N 天三口径 kline 增量（腾讯逐只，约 15k 请求，10 分钟内）。

用法：
  python scripts/incremental_stock_quotes.py --mode daily
  python scripts/incremental_stock_quotes.py --mode weekly --days 40 --threads 6
"""
from __future__ import annotations

import argparse
import os
import sys
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import date, datetime, timedelta, timezone

import psycopg
import requests

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, REPO)
sys.stdout.reconfigure(encoding="utf-8")

UA = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/120.0 Safari/537.36"}
QT = "https://qt.gtimg.cn/q="
KLINE = "https://web.ifzq.gtimg.cn/appstock/app/fqkline/get"
CN = timezone(timedelta(hours=8))


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
    host = os.getenv("BP_ETL_DB_HOST") or "127.0.0.1"
    conn = psycopg.connect(host=host, port=int(env.get("PGPORT", "5432")),
        dbname=env.get("PGDATABASE", "postgres"), user=env.get("PGUSER", "postgres"),
        password=env.get("PGPASSWORD", ""))
    with conn.cursor() as cur:
        cur.execute("SET synchronous_commit = off")
    conn.commit()
    return conn


def tencent_symbol(code: str, market: str) -> str:
    market = (market or "").upper()
    if market == "SH" or (not market and code.startswith(("6", "9"))):
        return "sh" + code
    if market == "BJ":
        return "bj" + code
    return "sz" + code


def universe():
    with db_conn() as conn, conn.cursor() as cur:
        cur.execute("SELECT stock_code, market FROM bp_stock_master WHERE stock_code ~ '^[0-9]{6}$' ORDER BY stock_code")
        return [(r[0], r[1]) for r in cur.fetchall()]


def upsert_rows(rows):
    if not rows:
        return 0
    sql = (
        "INSERT INTO bp_stock_quote_daily"
        " (symbol, trade_date, source, adjust, open, high, low, close, volume, amount, pct_change)"
        " VALUES (%s, %s, 'tencent_qt', %s, %s, %s, %s, %s, %s, %s, %s)"
        " ON CONFLICT (symbol, trade_date, source, adjust) DO UPDATE SET"
        " open=EXCLUDED.open, high=EXCLUDED.high, low=EXCLUDED.low, close=EXCLUDED.close,"
        " volume=EXCLUDED.volume, amount=EXCLUDED.amount, pct_change=EXCLUDED.pct_change"
    )
    conn = db_conn()
    try:
        with conn.cursor() as cur:
            cur.executemany(sql, rows)
        conn.commit()
    finally:
        conn.close()
    return len(rows)


def run_daily() -> int:
    today = datetime.now(CN).date()
    now = datetime.now(CN)
    if now.hour < 15 or (now.hour == 15 and now.minute < 10):
        print("skip: 收盘确认前（15:10 后运行）")
        return 0
    stocks = universe()
    session = requests.Session()
    session.headers.update(UA)
    rows = []
    for start in range(0, len(stocks), 60):
        chunk = stocks[start:start + 60]
        symbols = ",".join(tencent_symbol(code, market) for code, market in chunk)
        try:
            response = session.get(QT + symbols, timeout=15)
            response.encoding = "gbk"
            text = response.text
        except Exception as exc:  # noqa: BLE001
            print("batch fail", start, type(exc).__name__)
            continue
        for line in text.split(";"):
            line = line.strip()
            if not line or "=" not in line:
                continue
            key, raw = line.split("=", 1)
            raw = raw.strip().strip('"')
            parts = raw.split("~")
            if len(parts) < 38:
                continue
            code = parts[2]
            try:
                current = float(parts[3])
                open_ = float(parts[5]) if parts[5] else 0.0
                high = float(parts[33]) if parts[33] else 0.0
                low = float(parts[34]) if parts[34] else 0.0
                volume = int(float(parts[36]) * 100) if parts[36] else 0
                amount = float(parts[37]) * 10000.0 if parts[37] else None
                pct = float(parts[32]) if parts[32] else None
                stamp = parts[30]
                trade_date = date(int(stamp[0:4]), int(stamp[4:6]), int(stamp[6:8]))
            except (ValueError, IndexError):
                continue
            if trade_date != today or current <= 0:
                continue
            rows.append((code, trade_date, "bfq", open_, high, low, current, volume, amount, pct))
        time.sleep(0.05)
    written = upsert_rows(rows)
    print(f"daily bfq rows={written} date={today} universe={len(stocks)}")
    return 0


def fetch_kline_chunk(session, symbol: str, start: date, end: date, adjust: str):
    kind = "" if adjust == "bfq" else adjust
    params = ",".join([symbol, "day", start.isoformat(), end.isoformat(), "640", kind])
    try:
        response = session.get(KLINE, params={"param": params}, timeout=20)
        payload = response.json()
    except Exception:
        return []
    data = (payload.get("data") or {}).get(symbol) or {}
    key = {"bfq": "day", "qfq": "qfqday", "hfq": "hfqday"}[adjust]
    out = []
    for row in data.get(key) or []:
        try:
            out.append((symbol, date.fromisoformat(str(row[0])[:10]), adjust,
                        float(row[1]), float(row[3]), float(row[4]), float(row[2]), int(float(row[5]))))
        except (ValueError, IndexError, TypeError):
            continue
    return out


def run_weekly(days: int, threads: int, start_year: int | None = None) -> int:
    end = datetime.now(CN).date()
    start = date(start_year, 1, 1) if start_year else end - timedelta(days=days)
    stocks = universe()
    tasks = [(code, market, adjust) for code, market in stocks for adjust in ("bfq", "qfq", "hfq")]
    sql = (
        "INSERT INTO bp_stock_quote_daily"
        " (symbol, trade_date, source, adjust, open, high, low, close, volume)"
        " VALUES (%s, %s, 'tencent_kline', %s, %s, %s, %s, %s, %s)"
        " ON CONFLICT (symbol, trade_date, source, adjust) DO UPDATE SET"
        " open=EXCLUDED.open, high=EXCLUDED.high, low=EXCLUDED.low, close=EXCLUDED.close, volume=EXCLUDED.volume"
    )
    done = {"ok": 0, "rows": 0}

    def worker(code, market, adjust):
        session = requests.Session()
        session.headers.update(UA)
        rows = []
        cursor = start
        while cursor <= end:
            chunk_end = min(date(cursor.year + 2, 12, 31), end)
            rows.extend(fetch_kline_chunk(session, tencent_symbol(code, market), cursor, chunk_end, adjust))
            cursor = chunk_end + timedelta(days=1)
        dedup = {row[1]: row for row in rows}
        rows = [dedup[key] for key in sorted(dedup)]
        if rows:
            conn = db_conn()
            try:
                with conn.cursor() as cur:
                    cur.executemany(sql, [r[:8] for r in rows])
                conn.commit()
            finally:
                conn.close()
            done["rows"] += len(rows)
        done["ok"] += 1

    with ThreadPoolExecutor(max_workers=threads) as pool:
        futures = [pool.submit(worker, *task) for task in tasks]
        for future in as_completed(futures):
            future.result()
    print(f"weekly rows={done['rows']} tasks={done['ok']} window={start}..{end}")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--mode", choices=["daily", "weekly"], default="daily")
    parser.add_argument("--days", type=int, default=40)
    parser.add_argument("--start-year", type=int, default=0)
    parser.add_argument("--threads", type=int, default=6)
    args = parser.parse_args()
    return run_daily() if args.mode == "daily" else run_weekly(args.days, args.threads, args.start_year or None)


if __name__ == "__main__":
    raise SystemExit(main())
