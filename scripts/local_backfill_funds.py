# -*- coding: utf-8 -*-
"""本机全量回填基金净值（天天基金 pingzhongdata）→ 生产库 bp_fund_nav_daily。

用法：
    python scripts/local_backfill_funds.py --threads 8
    python scripts/local_backfill_funds.py --limit 50           # 小样本
    python scripts/local_backfill_funds.py --etf-only           # 仅 ETF/指数基金
断点续跑：默认跳过已存在净值的基金；--force 强制重抓。
"""
from __future__ import annotations

import argparse
import json
import os
import re
import sys
import threading
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import date, datetime, timedelta, timezone

import psycopg
import requests

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, REPO)
sys.stdout.reconfigure(encoding="utf-8")

FUND_LIST_URL = "https://fund.eastmoney.com/js/fundcode_search.js"
NAV_URL = "https://fund.eastmoney.com/pingzhongdata/{code}.js"
UA = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/120.0 Safari/537.36", "Referer": "https://fund.eastmoney.com/"}
CN_TZ = timezone(timedelta(hours=8))
LOCK = threading.Lock()
PROGRESS = {"ok": 0, "failed": 0, "rows": 0}
local = threading.local()


def thread_conn():
    conn = getattr(local, "conn", None)
    if conn is None or conn.closed:
        conn = db_conn()
        local.conn = conn
        local.pending = 0
    return conn


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
        values[key.strip()] = value.split(" #")[0].strip().strip('"').strip("'")
    return values


def db_conn():
    env = load_env()
    host = os.getenv("BP_BACKFILL_DB_HOST") or "81.71.158.239"
    conninfo = (
        "host=" + host + " port=" + str(env.get("PGPORT", "5432"))
        + " dbname=" + env.get("PGDATABASE", "postgres")
        + " user=" + env.get("PGUSER", "postgres")
        + " password=" + env.get("PGPASSWORD", "")
    )
    conn = psycopg.connect(conninfo)
    with conn.cursor() as cur:
        cur.execute("SET synchronous_commit = off")
    conn.commit()
    return conn


def fetch_fund_list() -> list[tuple[str, str, str]]:
    response = requests.get(FUND_LIST_URL, headers=UA, timeout=30)
    response.raise_for_status()
    match = re.search(r"var\s+r\s*=\s*(\[.*\]);", response.text, re.S)
    if not match:
        raise RuntimeError("fund list parse failed")
    rows = json.loads(match.group(1))
    out = []
    for row in rows:
        if isinstance(row, list) and len(row) >= 4:
            out.append((row[0], row[2], row[3]))
    return out


def parse_nav(text: str):
    match = re.search(r"Data_netWorthTrend\s*=\s*(\[.*?\]);", text)
    if not match:
        return []
    try:
        rows = json.loads(match.group(1))
    except json.JSONDecodeError:
        return []
    out = []
    for item in rows:
        try:
            trade_date = datetime.fromtimestamp(int(item["x"]) / 1000.0, tz=CN_TZ).date()
            value = float(item["y"])
        except (KeyError, TypeError, ValueError, OSError):
            continue
        out.append((trade_date, value))
    return out


def write_fund(code: str, name: str, fund_type: str, nav_rows) -> int:
    is_etf = "ETF" in fund_type or "指数型" in fund_type
    conn = thread_conn()
    with conn.cursor() as cur:
        cur.execute(
            "INSERT INTO bp_fund_master (fund_code, name, is_etf) VALUES (%s, %s, %s)"
            " ON CONFLICT (fund_code) DO UPDATE SET name = EXCLUDED.name, is_etf = bp_fund_master.is_etf OR EXCLUDED.is_etf",
            (code, name, is_etf),
        )
        payload = [(code, d, v, "em_pingzhongdata") for d, v in nav_rows]
        cur.executemany(
            "INSERT INTO bp_fund_nav_daily (fund_code, trade_date, nav, source) VALUES (%s, %s, %s, %s)"
            " ON CONFLICT (fund_code, trade_date) DO UPDATE SET nav = EXCLUDED.nav",
            payload,
        )
    local.pending = getattr(local, "pending", 0) + 1
    if local.pending >= 10:
        conn.commit()
        local.pending = 0
    return len(payload)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--threads", type=int, default=12)
    parser.add_argument("--limit", type=int, default=0)
    parser.add_argument("--etf-only", action="store_true")
    parser.add_argument("--force", action="store_true")
    args = parser.parse_args()
    funds = fetch_fund_list()
    if args.etf_only:
        funds = [f for f in funds if "ETF" in f[2] or "指数型" in f[2]]
    if args.limit:
        funds = funds[: args.limit]
    with db_conn() as conn, conn.cursor() as cur:
        cur.execute("SELECT DISTINCT fund_code FROM bp_fund_nav_daily WHERE fund_code ~ '^[0-9]{6}$'")
        done = {row[0] for row in cur.fetchall()}
    targets = [f for f in funds if args.force or f[0] not in done]
    print(f"funds={len(funds)} targets={len(targets)} etf_only={args.etf_only}", flush=True)

    def worker(code: str, name: str, fund_type: str):
        session = requests.Session()
        session.headers.update(UA)
        try:
            response = session.get(NAV_URL.format(code=code), timeout=25)
            if response.status_code != 200 or len(response.text) < 500:
                raise RuntimeError("http " + str(response.status_code))
            nav_rows = parse_nav(response.text)
            if not nav_rows:
                raise RuntimeError("empty nav")
            written = write_fund(code, name, fund_type, nav_rows)
            with LOCK:
                PROGRESS["ok"] += 1
                PROGRESS["rows"] += written
                total = PROGRESS["ok"] + PROGRESS["failed"]
                if total % 200 == 0:
                    print(f"progress {total}/{len(targets)} ok={PROGRESS['ok']} fail={PROGRESS['failed']} rows={PROGRESS['rows']}", flush=True)
        except Exception as exc:  # noqa: BLE001
            with LOCK:
                PROGRESS["failed"] += 1
                print(f"fail {code} {type(exc).__name__} {str(exc)[:80]}", flush=True)
        time.sleep(0.05)

    started = time.time()
    with ThreadPoolExecutor(max_workers=args.threads) as pool:
        futures = [pool.submit(worker, *fund) for fund in targets]
        for future in as_completed(futures):
            future.result()
    print(f"done ok={PROGRESS['ok']} failed={PROGRESS['failed']} rows={PROGRESS['rows']} elapsed={int(time.time()-started)}s", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
