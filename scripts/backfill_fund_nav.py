# -*- coding: utf-8 -*-
"""回填/增量抓取基金净值（天天基金 pingzhongdata）→ bp_fund_nav_daily。

用法：
    python scripts/backfill_fund_nav.py                # 全量（跳过已有足够历史的基金）
    python scripts/backfill_fund_nav.py --force        # 强制重抓
    python scripts/backfill_fund_nav.py --fund 005827  # 单只调试
"""
from __future__ import annotations

import argparse
import json
import re
import sys
import threading
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import date, datetime, timedelta, timezone

import requests

sys.path.insert(0, "/opt/balanced-portfolio")
sys.stdout.reconfigure(encoding="utf-8")

from bp_ingest.config import load_config, setup_logging
from bp_ingest.db import connect

UA = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0 Safari/537.36",
    "Referer": "https://fundf10.eastmoney.com/",
}
URL = "https://fund.eastmoney.com/pingzhongdata/{code}.js"
CN_TZ = timezone(timedelta(hours=8))
BATCH = 200


def strip_prefix(code: str) -> str:
    return re.sub(r"^(SH|SZ|OF)", "", code)


def parse_nav(text: str):
    match = re.search(r"Data_netWorthTrend\s*=\s*(\[.*?\]);", text)
    if not match:
        return [], []
    try:
        rows = json.loads(match.group(1))
    except json.JSONDecodeError:
        return [], []
    nav_rows = []
    for item in rows:
        try:
            ts = int(item["x"]) / 1000.0
            trade_date = datetime.fromtimestamp(ts, tz=CN_TZ).date()
            value = float(item["y"])
        except (KeyError, TypeError, ValueError, OSError):
            continue
        nav_rows.append((trade_date, value))
    acc_rows = []
    acc_match = re.search(r"Data_ACWorthTrend\s*=\s*(\[.*?\]);", text)
    if acc_match:
        try:
            acc = json.loads(acc_match.group(1))
            for item in acc:
                if isinstance(item, list) and len(item) >= 2:
                    ts = int(item[0]) / 1000.0
                    acc_rows.append((datetime.fromtimestamp(ts, tz=CN_TZ).date(), float(item[1])))
        except (json.JSONDecodeError, TypeError, ValueError, OSError):
            acc_rows = []
    return nav_rows, acc_rows


def upsert_nav(conn, fund_code: str, nav_rows, acc_rows) -> int:
    acc_map = dict(acc_rows)
    payload = [
        (fund_code, trade_date, value, acc_map.get(trade_date))
        for trade_date, value in nav_rows
    ]
    if not payload:
        return 0
    with conn.cursor() as cur:
        cur.executemany(
            "INSERT INTO bp_fund_nav_daily (fund_code, trade_date, nav, acc_nav, source)"
            " VALUES (%s, %s, %s, %s, 'em_pingzhongdata')"
            " ON CONFLICT (fund_code, trade_date) DO UPDATE SET"
            " nav = EXCLUDED.nav, acc_nav = COALESCE(EXCLUDED.acc_nav, bp_fund_nav_daily.acc_nav)",
            payload,
        )
    return len(payload)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--force", action="store_true")
    parser.add_argument("--fund", type=str, default=None)
    parser.add_argument("--workers", type=int, default=8)
    args = parser.parse_args()
    setup_logging()
    cfg = load_config()
    with connect(cfg.db) as conn, conn.cursor() as cur:
        if args.fund:
            codes = [args.fund]
        else:
            cur.execute("SELECT DISTINCT fund_code FROM bp_index_tracker_fund ORDER BY 1")
            codes = [row[0] for row in cur.fetchall()]
        print("targets:", len(codes), flush=True)
        done = 0
        failed = 0
        lock = threading.Lock()
        counter = {"done": 0, "failed": 0}

        def worker(raw_code: str) -> None:
            code = strip_prefix(raw_code)
            if not args.force:
                with connect(cfg.db) as conn, conn.cursor() as cur:
                    cur.execute("SELECT max(trade_date) FROM bp_fund_nav_daily WHERE fund_code = %s", (raw_code,))
                    last = cur.fetchone()[0]
                if last is not None and last >= date.today() - timedelta(days=10):
                    return
            try:
                session = requests.Session()
                session.headers.update(UA)
                response = session.get(URL.format(code=code), timeout=30)
                if response.status_code != 200 or len(response.text) < 500:
                    raise RuntimeError("http " + str(response.status_code))
                nav_rows, acc_rows = parse_nav(response.text)
                if not nav_rows:
                    raise RuntimeError("empty nav")
                with connect(cfg.db) as conn:
                    conn.autocommit = False
                    upsert_nav(conn, raw_code, nav_rows, acc_rows)
                    conn.commit()
                with lock:
                    counter["done"] += 1
            except Exception as exc:  # noqa: BLE001
                with lock:
                    counter["failed"] += 1
                    print("fail", raw_code, type(exc).__name__, str(exc)[:80], flush=True)
            finally:
                with lock:
                    total = counter["done"] + counter["failed"]
                    if total % 100 == 0:
                        print("progress", total, "/", len(codes), "ok", counter["done"], "fail", counter["failed"], flush=True)
                time.sleep(0.05)

        with ThreadPoolExecutor(max_workers=args.workers) as pool:
            futures = [pool.submit(worker, code) for code in codes]
            for future in as_completed(futures):
                future.result()
        done = counter["done"]
        failed = counter["failed"]
    print("done:", done, "failed:", failed, flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
