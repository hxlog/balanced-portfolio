# -*- coding: utf-8 -*-
"""基金净值日增量（服务器运行）：天天基金 pingzhongdata → bp_fund_nav_daily。

默认只更新 bp_fund_master 中已有的基金（全量回填完成后即为全市场），
只写入最近 N 天，避免每天全量重写。断点：按最大净值日期跳过最近已更新的基金。

用法：python scripts/incremental_fund_nav.py --threads 6 --days 30
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
PROGRESS = {"ok": 0, "failed": 0, "rows": 0}


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


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--threads", type=int, default=6)
    parser.add_argument("--days", type=int, default=30)
    args = parser.parse_args()
    cutoff = datetime.now(CN).date() - timedelta(days=args.days)
    with db_conn() as conn, conn.cursor() as cur:
        cur.execute(
            "SELECT f.fund_code FROM bp_fund_master f"
            " WHERE NOT EXISTS ("
            "  SELECT 1 FROM bp_fund_nav_daily n WHERE n.fund_code=f.fund_code AND n.trade_date >= %s"
            " ) ORDER BY f.fund_code",
            (cutoff,),
        )
        targets = [row[0] for row in cur.fetchall()]
    print(f"targets={len(targets)} cutoff={cutoff}", flush=True)

    def worker(code: str):
        session = requests.Session()
        session.headers.update(UA)
        try:
            response = session.get("https://fund.eastmoney.com/pingzhongdata/" + code + ".js", timeout=25)
            if response.status_code != 200 or len(response.text) < 500:
                raise RuntimeError("http " + str(response.status_code))
            navs = [row for row in parse_nav(response.text) if row[0] >= cutoff]
            if not navs:
                raise RuntimeError("empty")
            with db_conn() as conn, conn.cursor() as cur:
                cur.executemany(
                    "INSERT INTO bp_fund_nav_daily (fund_code, trade_date, nav, source) VALUES (%s, %s, %s, 'em_pingzhongdata')"
                    " ON CONFLICT (fund_code, trade_date) DO UPDATE SET nav = EXCLUDED.nav",
                    [(code, d, v) for d, v in navs],
                )
            conn.commit()
            with LOCK:
                PROGRESS["ok"] += 1
                PROGRESS["rows"] += len(navs)
        except Exception:  # noqa: BLE001
            with LOCK:
                PROGRESS["failed"] += 1
        time.sleep(0.05)

    started = time.time()
    with ThreadPoolExecutor(max_workers=args.threads) as pool:
        futures = [pool.submit(worker, code) for code in targets]
        for future in as_completed(futures):
            future.result()
    print(f"done ok={PROGRESS['ok']} failed={PROGRESS['failed']} rows={PROGRESS['rows']} elapsed={int(time.time()-started)}s", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
