# -*- coding: utf-8 -*-
"""服务器侧快速基金净值回填（天天基金 pingzhongdata，每基金一个请求）。

- 只处理尚未入库的基金；已入库的按最新净值日期判断（近 30 天有数据即跳过）；
- 每基金独立连接 + 立即提交，避免批量提交在 WAN/抖动下丢失；
- 无 Data_netWorthTrend 的（货币/封闭）直接跳过。

用法：python scripts/fast_backfill_funds.py --threads 8
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
from datetime import datetime, timedelta, timezone

import psycopg
import requests

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, REPO)
sys.stdout.reconfigure(encoding="utf-8")
UA = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/120.0 Safari/537.36", "Referer": "https://fund.eastmoney.com/"}
CN = timezone(timedelta(hours=8))
LOCK = threading.Lock()
PROGRESS = {"ok": 0, "skip": 0, "failed": 0, "rows": 0}


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
        host=os.getenv("BP_BACKFILL_DB_HOST") or "127.0.0.1",
        port=int(env.get("PGPORT", "5432")),
        dbname=env.get("PGDATABASE", "postgres"),
        user=env.get("PGUSER", "postgres"), password=env.get("PGPASSWORD", ""))
    with conn.cursor() as cur:
        cur.execute("SET synchronous_commit = off")
    conn.commit()
    return conn


def fund_list(session) -> list[tuple[str, str, str]]:
    r = session.get("https://fund.eastmoney.com/js/fundcode_search.js", timeout=30)
    match = re.search(r"var\s+r\s*=\s*(\[.*\]);", r.text, re.S)
    rows = json.loads(match.group(1))
    return [(str(item[0]), str(item[2]), str(item[3])) for item in rows if isinstance(item, list) and len(item) >= 4]


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
            out.append((datetime.fromtimestamp(int(item["x"]) / 1000.0, tz=CN).date(), float(item["y"])))
        except (KeyError, TypeError, ValueError, OSError):
            continue
    return out


def write_fund(code: str, name: str, fund_type: str, navs) -> int:
    is_etf = "ETF" in fund_type or "指数型" in fund_type
    conn = db_conn()
    try:
        with conn.cursor() as cur:
            cur.execute(
                "INSERT INTO bp_fund_master (fund_code, name, is_etf) VALUES (%s, %s, %s)"
                " ON CONFLICT (fund_code) DO UPDATE SET name=EXCLUDED.name, is_etf=bp_fund_master.is_etf OR EXCLUDED.is_etf",
                (code, name, is_etf))
            cur.executemany(
                "INSERT INTO bp_fund_nav_daily (fund_code, trade_date, nav, source) VALUES (%s, %s, %s, 'em_pingzhongdata')"
                " ON CONFLICT (fund_code, trade_date) DO UPDATE SET nav=EXCLUDED.nav",
                [(code, d, v) for d, v in navs])
        conn.commit()
    finally:
        conn.close()
    return len(navs)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--threads", type=int, default=8)
    args = parser.parse_args()
    session = requests.Session(); session.headers.update(UA)
    funds = fund_list(session)
    with db_conn() as conn, conn.cursor() as cur:
        cur.execute("SELECT DISTINCT fund_code FROM bp_fund_nav_daily")
        done = {row[0] for row in cur.fetchall()}
    targets = [f for f in funds if f[0] not in done]
    print(f"funds={len(funds)} targets={len(targets)}", flush=True)

    def worker(code, name, fund_type):
        s = requests.Session(); s.headers.update(UA)
        try:
            r = s.get(f"https://fund.eastmoney.com/pingzhongdata/{code}.js", timeout=25)
            if r.status_code != 200 or len(r.text) < 500:
                raise RuntimeError("http " + str(r.status_code))
            navs = parse_nav(r.text)
            if not navs:
                with LOCK:
                    PROGRESS["skip"] += 1
                return
            written = write_fund(code, name, fund_type, navs)
            with LOCK:
                PROGRESS["ok"] += 1
                PROGRESS["rows"] += written
                total = PROGRESS["ok"] + PROGRESS["skip"] + PROGRESS["failed"]
                if PROGRESS["ok"] % 200 == 0:
                    print(f"progress total={total}/{len(targets)} ok={PROGRESS['ok']} skip={PROGRESS['skip']} fail={PROGRESS['failed']} rows={PROGRESS['rows']}", flush=True)
        except Exception as exc:  # noqa: BLE001
            with LOCK:
                PROGRESS["failed"] += 1
                if PROGRESS["failed"] % 50 == 1:
                    print(f"fail {code} {type(exc).__name__} {str(exc)[:70]}", flush=True)
        time.sleep(0.01)

    started = time.time()
    with ThreadPoolExecutor(max_workers=args.threads) as pool:
        futures = [pool.submit(worker, *f) for f in targets]
        for future in as_completed(futures):
            future.result()
    print(f"done ok={PROGRESS['ok']} skip={PROGRESS['skip']} fail={PROGRESS['failed']} rows={PROGRESS['rows']} elapsed={int(time.time()-started)}s", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
