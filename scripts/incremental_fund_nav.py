# -*- coding: utf-8 -*-
"""基金净值全量日更（服务器运行）：东方财富公开接口 → bp_fund_nav_daily。

两条互补链路（覆盖全市场 2.8 万只基金）：

1) rankhandler 批量榜（42 页 × 500 只，约 2~3 分钟/次）：拿到全部「开放基金」
   的最新净值，一次请求覆盖 2 万只，避免逐只抓取；
2) lsjz 逐只补缺（约 4KB/只）：对「最新净值落后于目标交易日」的基金补最近 30 天，
   覆盖 ETF/LOF/封闭式/rankhandler 未收录的基金，并顺带补上停更后恢复的基金。

用法：
  python scripts/incremental_fund_nav.py                 # 日更（rankhandler + 缺日补抓）
  python scripts/incremental_fund_nav.py --gap-only      # 只补缺（不拉批量榜）
  python scripts/incremental_fund_nav.py --gap-limit 5000
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

UA = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/120.0 Safari/537.36"}
RANK_URL = "https://fund.eastmoney.com/data/rankhandler.aspx"
RANK_REFERER = "https://fund.eastmoney.com/data/fundranking.html"
LSJZ_URL = "https://api.fund.eastmoney.com/f10/lsjz"
LSJZ_REFERER = "https://fundf10.eastmoney.com/"
CN = timezone(timedelta(hours=8))
PAGE_SIZE = 500
PROGRESS = {"ok": 0, "failed": 0, "rows": 0}
LOCK = threading.Lock()
FAILURES: list[str] = []
_MIN_INTERVAL = float(os.getenv("BP_FUND_MIN_INTERVAL", "0.04"))
_RATE_LOCK = threading.Lock()
_LAST_REQUEST = [0.0]

UPSERT_SQL = (
    "INSERT INTO bp_fund_nav_daily (fund_code, trade_date, nav, acc_nav, source)"
    " VALUES (%s, %s, %s, %s, %s)"
    " ON CONFLICT (fund_code, trade_date) DO UPDATE SET nav=EXCLUDED.nav,"
    " acc_nav=COALESCE(EXCLUDED.acc_nav, bp_fund_nav_daily.acc_nav), source=EXCLUDED.source"
)


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


def db_conn() -> psycopg.Connection:
    env = load_env()
    conn = psycopg.connect(
        host=os.getenv("BP_ETL_DB_HOST") or "127.0.0.1",
        port=int(env.get("PGPORT", "5432")),
        dbname=env.get("PGDATABASE", "postgres"),
        user=env.get("PGUSER", "postgres"),
        password=env.get("PGPASSWORD", ""),
    )
    with conn.cursor() as cur:
        cur.execute("SET synchronous_commit = off")
    conn.commit()
    return conn


def _throttle() -> None:
    with _RATE_LOCK:
        wait = _MIN_INTERVAL - (time.time() - _LAST_REQUEST[0])
        if wait > 0:
            time.sleep(wait)
        _LAST_REQUEST[0] = time.time()


def latest_trading_date(conn: psycopg.Connection) -> date:
    """A 股交易日历里 <= 今天的最新交易日；日历缺失时退化为工作日。"""
    with conn.cursor() as cur:
        cur.execute(
            "SELECT max(cal_date) FROM bp_trading_calendar"
            " WHERE market = 'CN' AND is_trading AND cal_date <= %s",
            (datetime.now(CN).date(),),
        )
        row = cur.fetchone()
    if row and row[0]:
        return row[0]
    today = datetime.now(CN).date()
    while today.weekday() >= 5:
        today -= timedelta(days=1)
    return today


def fetch_rankhandler_page(session: requests.Session, page: int) -> tuple[list[tuple], int]:
    """返回 (rows, all_pages)。rows = (fund_code, trade_date, nav, acc_nav)。"""
    params = {
        "op": "ph",
        "dt": "kf",
        "ft": "all",
        "rs": "",
        "gs": "0",
        "sc": "1nzf",
        "st": "desc",
        "sd": "",
        "ed": "",
        "qdii": "",
        "tabSubtype": ",,,,",
        "pi": str(page),
        "pn": str(PAGE_SIZE),
        "dx": "1",
        "v": "0.1",
    }
    for attempt in range(3):
        try:
            _throttle()
            response = session.get(
                RANK_URL, params=params, headers={"Referer": RANK_REFERER}, timeout=30
            )
            response.raise_for_status()
            text = response.text
            break
        except Exception:  # noqa: BLE001
            time.sleep(1.5 * (attempt + 1))
    else:
        return [], 0
    all_pages = 0
    match = re.search(r"allPages:(\d+)", text)
    if match:
        all_pages = int(match.group(1))
    block = re.search(r"datas:\[(.*?)\],allRecords", text, re.S)
    if not block:
        return [], all_pages
    rows: list[tuple] = []
    for item in re.findall(r'"([^"]+)"', block.group(1)):
        parts = item.split(",")
        if len(parts) < 6:
            continue
        code = parts[0].strip()
        try:
            trade_date = date.fromisoformat(parts[3].strip())
        except ValueError:
            continue
        def _num(value: str):
            text_value = (value or "").strip()
            return float(text_value) if text_value else None
        nav, acc_nav = _num(parts[4]), _num(parts[5])
        if nav is None:
            continue
        rows.append((code, trade_date, nav, acc_nav))
    return rows, all_pages


def run_rankhandler(conn: psycopg.Connection, target: date) -> int:
    """批量榜：一次覆盖全部开放基金的最新净值。"""
    session = requests.Session()
    session.headers.update(UA)
    rows, all_pages = fetch_rankhandler_page(session, 1)
    if not rows:
        print("rankhandler page1 empty", flush=True)
        return 0
    pages = max(all_pages, 1)
    for page in range(2, pages + 1):
        page_rows, _ = fetch_rankhandler_page(session, page)
        if not page_rows:
            break
        rows.extend(page_rows)
    payload = [(code, trade_date, nav, acc, "em_rankhandler") for code, trade_date, nav, acc in rows]
    with conn.cursor() as cur:
        cur.executemany(UPSERT_SQL, payload)
    conn.commit()
    print(f"rankhandler rows={len(payload)} pages={pages} target={target}", flush=True)
    return len(payload)


def stale_funds(conn: psycopg.Connection, target: date, limit: int) -> list[str]:
    """最新净值落后于目标交易日的基金（按落后天数倒序，先补最陈旧的）。"""
    with conn.cursor() as cur:
        cur.execute(
            "SELECT f.fund_code, max(n.trade_date) AS last_date"
            " FROM bp_fund_master f LEFT JOIN bp_fund_nav_daily n ON n.fund_code = f.fund_code"
            " GROUP BY f.fund_code HAVING max(n.trade_date) IS NULL OR max(n.trade_date) < %s"
            " ORDER BY last_date NULLS FIRST, f.fund_code LIMIT %s",
            (target, limit),
        )
        return [row[0] for row in cur.fetchall()]


def fetch_lsjz(session: requests.Session, code: str, page_size: int = 30) -> list[tuple]:
    """单只基金最近 N 条净值：[(fund_code, trade_date, nav, acc_nav)]。"""
    params = {"fundCode": code, "pageIndex": "1", "pageSize": str(page_size)}
    for attempt in range(3):
        try:
            _throttle()
            response = session.get(
                LSJZ_URL, params=params, headers={"Referer": LSJZ_REFERER}, timeout=25
            )
            if response.status_code != 200:
                raise RuntimeError(f"http {response.status_code}")
            payload = response.json()
            break
        except Exception:  # noqa: BLE001
            time.sleep(1.0 * (attempt + 1))
    else:
        return []
    items = ((payload or {}).get("Data") or {}).get("LSJZList") or []
    out: list[tuple] = []
    for item in items:
        try:
            trade_date = date.fromisoformat(str(item.get("FSRQ") or "")[:10])
        except ValueError:
            continue
        nav_text = str(item.get("DWJZ") or "").strip()
        acc_text = str(item.get("LJJZ") or "").strip()
        try:
            nav = float(nav_text) if nav_text else None
        except ValueError:
            nav = None
        try:
            acc_nav = float(acc_text) if acc_text else None
        except ValueError:
            acc_nav = None
        if nav is None:
            continue
        out.append((code, trade_date, nav, acc_nav))
    return out


def funds_missing_recent_days(conn: psycopg.Connection, days: int, limit: int) -> list[str]:
    """最近 N 个交易日里任意一天缺净值的基金（覆盖率口径，含 rankhandler 未覆盖的基金）。"""
    with conn.cursor() as cur:
        cur.execute(
            "WITH tdays AS ("
            "  SELECT cal_date FROM bp_trading_calendar WHERE market = 'CN' AND is_trading"
            "  AND cal_date <= current_date ORDER BY cal_date DESC LIMIT %s"
            "), first_day AS (SELECT min(cal_date) AS d FROM tdays)"
            " SELECT f.fund_code FROM bp_fund_master f"
            " LEFT JOIN bp_fund_nav_daily n ON n.fund_code = f.fund_code"
            "   AND n.trade_date >= (SELECT d FROM first_day)"
            " GROUP BY f.fund_code"
            " HAVING count(n.trade_date) < (SELECT count(*) FROM tdays)"
            " ORDER BY f.fund_code LIMIT %s",
            (days, limit),
        )
        return [row[0] for row in cur.fetchall()]


def fill_funds(conn: psycopg.Connection, funds: list[str], target: date, threads: int, days: int) -> int:
    if not funds:
        return 0
    cutoff = target - timedelta(days=max(days, 3) * 2)
    print(f"gap fill funds={len(funds)} target={target} lookback={days}d", flush=True)
    local = threading.local()

    def thread_conn() -> psycopg.Connection:
        conn_local = getattr(local, "conn", None)
        if conn_local is None or conn_local.closed:
            conn_local = db_conn()
            local.conn = conn_local
        return conn_local

    def worker(code: str) -> None:
        session = requests.Session()
        session.headers.update(UA)
        rows = fetch_lsjz(session, code)
        rows = [row for row in rows if row[1] >= cutoff]
        if rows:
            conn_local = thread_conn()
            with conn_local.cursor() as cur:
                cur.executemany(
                    UPSERT_SQL,
                    [(c, d, nav, acc, "em_lsjz") for c, d, nav, acc in rows],
                )
            conn_local.commit()
        with LOCK:
            PROGRESS["ok"] += 1
            PROGRESS["rows"] += len(rows)
            if PROGRESS["ok"] % 500 == 0:
                print(f"gap progress {PROGRESS['ok']}/{len(funds)} rows={PROGRESS['rows']}", flush=True)

    with ThreadPoolExecutor(max_workers=threads) as pool:
        futures = [pool.submit(worker, code) for code in funds]
        for future in as_completed(futures):
            try:
                future.result()
            except Exception as exc:  # noqa: BLE001
                with LOCK:
                    PROGRESS["failed"] += 1
                    FAILURES.append(f"{type(exc).__name__} {str(exc)[:100]}")
    if FAILURES:
        log_dir = os.path.join(REPO, "logs")
        os.makedirs(log_dir, exist_ok=True)
        fail_path = os.path.join(log_dir, f"fund-nav-failures-{target.isoformat()}.txt")
        with open(fail_path, "w", encoding="utf-8") as handle:
            handle.write("\n".join(FAILURES))
        print(f"failures written to {fail_path} ({len(FAILURES)})", flush=True)
    return PROGRESS["rows"]


def run_gap_fill(conn: psycopg.Connection, target: date, limit: int, threads: int, days: int) -> int:
    funds = stale_funds(conn, target, limit)
    return fill_funds(conn, funds, target, threads, days)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--gap-only", action="store_true", help="只补缺，不拉 rankhandler 批量榜")
    parser.add_argument("--gap-limit", type=int, default=32000, help="单次补缺基金上限")
    parser.add_argument("--days", type=int, default=40, help="补缺回看天数")
    parser.add_argument(
        "--fill-days",
        type=int,
        default=0,
        help="按最近 N 个交易日覆盖率补缺口（对所有基金逐只补，单次修复历史空洞用）",
    )
    parser.add_argument("--threads", type=int, default=8)
    args = parser.parse_args()
    started = time.time()
    conn = db_conn()
    try:
        target = latest_trading_date(conn)
        rank_rows = 0 if args.gap_only else run_rankhandler(conn, target)
        if args.fill_days > 0:
            funds = funds_missing_recent_days(conn, args.fill_days, args.gap_limit)
            print(f"coverage fill days={args.fill_days} funds={len(funds)}", flush=True)
            gap_rows = fill_funds(conn, funds, target, args.threads, args.fill_days)
        else:
            gap_rows = run_gap_fill(conn, target, args.gap_limit, args.threads, args.days)
    finally:
        conn.close()
    print(
        f"done rank={rank_rows} gap_rows={gap_rows} ok={PROGRESS['ok']}"
        f" failed={PROGRESS['failed']} elapsed={int(time.time() - started)}s target={target}",
        flush=True,
    )
    return 0 if PROGRESS["failed"] == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
