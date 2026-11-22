# -*- coding: utf-8 -*-
"""港股个股日线 ETL：腾讯行情（bfq/qfq/hfq）→ bp_stock_quote_daily。

模式：
  --mode backfill  全量/补缺历史（腾讯 fqkline 不复权、hkfqkline 前/后复权，按 end 倒序分页）
  --mode daily     收盘后批量快照，仅写当日 bfq（腾讯 qt.gtimg.cn，60 只/请求）
  --mode weekly    近 N 天三口径增量（复权因子变化时刷新近端）

用法：
  python scripts/hk_stock_quotes.py --mode backfill --threads 10
  python scripts/hk_stock_quotes.py --mode backfill --codes 00700,02020
  python scripts/hk_stock_quotes.py --mode daily
  python scripts/hk_stock_quotes.py --mode weekly --days 40 --threads 8
"""
from __future__ import annotations

import argparse
import os
import sys
import threading
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import date, datetime, timedelta, timezone
from typing import Iterable, Sequence

import psycopg
import requests

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, REPO)
sys.stdout.reconfigure(encoding="utf-8")

UA = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/120.0 Safari/537.36"}
QT = "https://qt.gtimg.cn/q="
KLINE = "https://ifzq.gtimg.cn/appstock/app/fqkline/get"
KLINE_ALT = "https://proxy.finance.qq.com/ifzqgtimg/appstock/app/fqkline/get"
HK_KLINE = "https://ifzq.gtimg.cn/appstock/app/hkfqkline/get"
HK_KLINE_ALT = "https://proxy.finance.qq.com/ifzqgtimg/appstock/app/hkfqkline/get"
SOURCE_KLINE = "tencent_hk_kline"
SOURCE_QT = "tencent_hk_qt"
SOURCE_SINA = "sina_hk_kline"
CN = timezone(timedelta(hours=8))
PAGE_SIZE = 1000
LOCK = threading.Lock()
PROGRESS = {"ok": 0, "failed": 0, "rows": 0}
FAILURES: list[str] = []
DAILY_ROWS = [0]  # 最近一次 daily 写入行数（auto 源降级判断用）
# 全局限速：腾讯 web.ifzq 在批量请求下会触发 WAF（实测 450+ 任务后大量空响应）。
# 所有线程共用一个最小请求间隔，保 QoS 而不是靠单线程 sleep。
_MIN_INTERVAL = float(os.getenv("BP_HK_MIN_INTERVAL", "0.06"))
_RATE_LOCK = threading.Lock()
_LAST_REQUEST = [0.0]


def _throttled_get(session: requests.Session, url: str, **kwargs):
    with _RATE_LOCK:
        wait = _MIN_INTERVAL - (time.time() - _LAST_REQUEST[0])
        if wait > 0:
            time.sleep(wait)
        _LAST_REQUEST[0] = time.time()
    from bp_ingest.http_deadline import get_with_deadline

    return get_with_deadline(session, url, **kwargs)


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
    host = os.getenv("BP_ETL_DB_HOST") or "127.0.0.1"
    conn = psycopg.connect(
        host=host,
        port=int(env.get("PGPORT", "5432")),
        dbname=env.get("PGDATABASE", "postgres"),
        user=env.get("PGUSER", "postgres"),
        password=env.get("PGPASSWORD", ""),
    )
    with conn.cursor() as cur:
        cur.execute("SET synchronous_commit = off")
    conn.commit()
    return conn


def hk_universe(codes: Sequence[str] | None = None) -> list[str]:
    with db_conn() as conn, conn.cursor() as cur:
        if codes:
            cur.execute(
                "SELECT stock_code FROM bp_stock_master WHERE market='HK' AND stock_code = ANY(%s) ORDER BY stock_code",
                (list(codes),),
            )
        else:
            cur.execute(
                "SELECT stock_code FROM bp_stock_master WHERE market='HK' AND NOT is_delisted ORDER BY stock_code"
            )
        return [row[0] for row in cur.fetchall()]


def parse_kline_rows(rows: Iterable[Sequence]) -> list[tuple]:
    out = []
    for row in rows:
        if not isinstance(row, list) or len(row) < 6:
            continue
        try:
            out.append(
                (
                    date.fromisoformat(str(row[0])[:10]),
                    float(row[1]),   # open
                    float(row[3]),   # high
                    float(row[4]),   # low
                    float(row[2]),   # close
                    int(float(row[5])),  # volume
                )
            )
        except (TypeError, ValueError, IndexError):
            continue
    return out


_CANDIDATES_BFQ = [
    (KLINE_ALT, "hk{code},day,,{end},{count},"),
    (KLINE, "hk{code},day,,{end},{count},"),
]
_CANDIDATES_ADJ = [
    (HK_KLINE_ALT, "hk{code},day,,,{count},{kind}"),
    (HK_KLINE, "hk{code},day,,{end},{count},{kind}"),
]


def fetch_page(
    session: requests.Session, code: str, adjust: str, end: date, count: int = PAGE_SIZE
) -> list[tuple]:
    kind = "" if adjust == "bfq" else adjust
    key = {"bfq": "day", "qfq": "qfqday", "hfq": "hfqday"}[adjust]
    templates = _CANDIDATES_BFQ if adjust == "bfq" else _CANDIDATES_ADJ
    for url, template in templates:
        param = template.format(code=code, end=end.isoformat(), count=count, kind=kind)
        for attempt in range(2):
            try:
                response = _throttled_get(session, url, params={"param": param}, timeout=20)
                response.raise_for_status()
                payload = response.json()
                data = (payload.get("data") or {}).get(f"hk{code}") or {}
                rows = data.get(key) or data.get("day") or []
                if rows:
                    return parse_kline_rows(rows)
                break
            except Exception:  # noqa: BLE001
                time.sleep(1.0 * (attempt + 1))
    return []


def fetch_range(
    session: requests.Session,
    code: str,
    adjust: str,
    end: date,
    stop_at: date | None = None,
    count: int = PAGE_SIZE,
    floor: date = date(1990, 1, 1),
) -> list[tuple]:
    """从 end 往过去翻页，直到 floor 或 stop_at 之前。"""
    rows: dict[date, tuple] = {}
    cursor = end
    while cursor >= floor:
        batch = fetch_page(session, code, adjust, cursor, count)
        if not batch:
            break
        for row in batch:
            rows[row[0]] = row
        first = batch[0][0]
        if stop_at is not None and first <= stop_at:
            break
        if first <= floor or first >= cursor:
            break
        cursor = first - timedelta(days=1)
        time.sleep(0.03)
    return [rows[key] for key in sorted(rows)]


def sina_series(code: str, adjust: str, start: date, end: date) -> list[tuple]:
    """新浪港股日线（akshare 本地计算 qfq/hfq），返回 (date, open, high, low, close, volume)。"""
    import akshare as ak

    try:
        df = ak.stock_hk_daily(symbol=code, adjust=("" if adjust == "bfq" else adjust))
    except Exception:  # noqa: BLE001
        return []
    if df is None or len(df) == 0:
        return []
    out: list[tuple] = []
    for _, row in df.iterrows():
        try:
            trade_date = row["date"]
            if hasattr(trade_date, "date"):
                trade_date = trade_date.date()
            if trade_date < start or trade_date > end:
                continue
            out.append(
                (
                    trade_date,
                    float(row["open"]),
                    float(row["high"]),
                    float(row["low"]),
                    float(row["close"]),
                    int(float(row["volume"])) if row.get("volume") == row.get("volume") else 0,
                )
            )
        except (TypeError, ValueError, KeyError, AttributeError):
            continue
    return out


def existing_range(conn: psycopg.Connection, code: str, adjust: str) -> tuple[date | None, date | None, int]:
    with conn.cursor() as cur:
        cur.execute(
            "SELECT min(trade_date), max(trade_date), count(*) FROM bp_stock_quote_daily"
            " WHERE symbol=%s AND adjust=%s AND source=%s",
            (code, adjust, SOURCE_KLINE),
        )
        row = cur.fetchone()
    return (row[0], row[1], int(row[2] or 0)) if row else (None, None, 0)


def previous_close(conn: psycopg.Connection, code: str, adjust: str, before: date) -> float | None:
    with conn.cursor() as cur:
        cur.execute(
            "SELECT close FROM bp_stock_quote_daily WHERE symbol=%s AND adjust=%s"
            " AND trade_date < %s ORDER BY trade_date DESC LIMIT 1",
            (code, adjust, before),
        )
        row = cur.fetchone()
    return float(row[0]) if row and row[0] is not None else None


INSERT_SQL = (
    "INSERT INTO bp_stock_quote_daily"
    " (symbol, trade_date, source, adjust, open, high, low, close, volume, pct_change)"
    " VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)"
    " ON CONFLICT (symbol, trade_date, source, adjust) DO UPDATE SET"
    " open=EXCLUDED.open, high=EXCLUDED.high, low=EXCLUDED.low, close=EXCLUDED.close,"
    " volume=EXCLUDED.volume, pct_change=EXCLUDED.pct_change, captured_at=now()"
)


def build_rows(
    conn: psycopg.Connection,
    code: str,
    adjust: str,
    series: list[tuple],
    source: str = SOURCE_KLINE,
) -> list[tuple]:
    if not series:
        return []
    series = sorted({row[0]: row for row in series}.values())
    prev = previous_close(conn, code, adjust, series[0][0])
    out = []
    for trade_date, open_, high, low, close_, volume in series:
        pct = None
        if prev is not None and prev > 0:
            pct = (close_ / prev - 1.0) * 100.0
        prev = close_
        out.append((code, trade_date, source, adjust, open_, high, low, close_, volume, pct))
    return out


def run_backfill(codes, adjusts, threads: int, force: bool, end: date, floor: date, source: str = "tencent") -> int:
    universe = hk_universe(codes)
    tasks = [(code, adjust) for code in universe for adjust in adjusts]
    print(f"backfill universe={len(universe)} tasks={len(tasks)} adjusts={adjusts} end={end} floor={floor}", flush=True)

    local = threading.local()

    def thread_conn() -> psycopg.Connection:
        conn = getattr(local, "conn", None)
        if conn is None or conn.closed:
            conn = db_conn()
            local.conn = conn
        return conn

    def worker(code: str, adjust: str):
        conn = thread_conn()
        session = requests.Session()
        session.headers.update(UA)
        min_d, max_d, count = existing_range(conn, code, adjust)
        series: list[tuple] = []
        if source == "sina":
            series = sina_series(code, adjust, floor, end)
            rows = build_rows(conn, code, adjust, series, source=SOURCE_SINA)
        else:
            if force or count == 0:
                series.extend(fetch_range(session, code, adjust, end, floor=floor))
            else:
                # 先补最近端（复权因子/最新收盘）
                series.extend(fetch_range(session, code, adjust, end, stop_at=max_d, floor=floor))
                # 再补更早的历史（只回溯到 floor，避免为 1986 年起的老股翻几十页触发 WAF）
                if min_d is not None and min_d > floor:
                    older = fetch_range(
                        session, code, adjust, min_d - timedelta(days=1), floor=floor
                    )
                    series.extend(older)
            rows = build_rows(conn, code, adjust, series)
        if not rows:
            raise RuntimeError("empty")
        with conn.cursor() as cur:
            cur.executemany(INSERT_SQL, rows)
        conn.commit()
        with LOCK:
            PROGRESS["ok"] += 1
            PROGRESS["rows"] += len(rows)
            total = PROGRESS["ok"] + PROGRESS["failed"]
            if total % 50 == 0:
                print(
                    f"progress {total}/{len(tasks)} ok={PROGRESS['ok']}"
                    f" fail={PROGRESS['failed']} rows={PROGRESS['rows']}",
                    flush=True,
                )

    started = time.time()
    with ThreadPoolExecutor(max_workers=threads) as pool:
        futures = [pool.submit(worker, code, adjust) for code, adjust in tasks]
        for future in as_completed(futures):
            try:
                future.result()
            except Exception as exc:  # noqa: BLE001
                with LOCK:
                    PROGRESS["failed"] += 1
                    FAILURES.append(f"{type(exc).__name__} {str(exc)[:120]}")
                    if PROGRESS["failed"] % 20 == 1:
                        print(f"fail {type(exc).__name__} {str(exc)[:80]}", flush=True)
    if FAILURES:
        log_dir = os.path.join(REPO, "logs")
        os.makedirs(log_dir, exist_ok=True)
        fail_path = os.path.join(log_dir, f"hk-failures-{end.isoformat()}.txt")
        with open(fail_path, "w", encoding="utf-8") as handle:
            handle.write("\n".join(FAILURES))
        print(f"failures written to {fail_path} ({len(FAILURES)})", flush=True)
    print(
        f"done ok={PROGRESS['ok']} failed={PROGRESS['failed']} rows={PROGRESS['rows']}"
        f" elapsed={int(time.time() - started)}s",
        flush=True,
    )
    return 0 if PROGRESS["failed"] == 0 else 1


def parse_qt_timestamp(stamp: str) -> tuple[date, datetime]:
    stamp = (stamp or "").strip()
    for fmt in ("%Y/%m/%d %H:%M:%S", "%Y%m%d%H%M%S"):
        try:
            dt = datetime.strptime(stamp, fmt)
            return dt.date(), dt
        except ValueError:
            continue
    raise ValueError(f"bad timestamp: {stamp!r}")


def run_daily(threads: int = 4) -> int:
    today = datetime.now(CN).date()
    now = datetime.now(CN)
    if now.hour < 16 or (now.hour == 16 and now.minute < 15):
        print("skip: 港股收盘确认前（16:15 后运行）")
        return 0
    stocks = hk_universe()
    session = requests.Session()
    session.headers.update(UA)
    rows: list[tuple] = []
    for start in range(0, len(stocks), 60):
        chunk = stocks[start:start + 60]
        symbols = ",".join("hk" + code for code in chunk)
        try:
            response = session.get(QT + symbols, timeout=20)
            response.encoding = "gbk"
            text = response.text
        except Exception as exc:  # noqa: BLE001
            print("batch fail", start, type(exc).__name__)
            continue
        for line in text.split(";"):
            line = line.strip()
            if not line or "=" not in line:
                continue
            raw = line.split("=", 1)[1].strip().strip('"')
            parts = raw.split("~")
            if len(parts) < 38:
                continue
            code = parts[2].zfill(5)
            try:
                current = float(parts[3])
                if current <= 0:
                    continue
                trade_date, _ = parse_qt_timestamp(parts[30])
                if trade_date != today:
                    continue
                open_ = float(parts[5]) if parts[5] else 0.0
                high = float(parts[33]) if parts[33] else 0.0
                low = float(parts[34]) if parts[34] else 0.0
                volume = int(float(parts[36])) if parts[36] else 0
                pct = float(parts[32]) if parts[32] else None
            except (ValueError, IndexError):
                continue
            rows.append((code, trade_date, SOURCE_QT, "bfq", open_, high, low, current, volume, pct))
        time.sleep(0.05)
    if not rows:
        print(f"daily hk rows=0 date={today} universe={len(stocks)}")
        return 0
    with db_conn() as conn, conn.cursor() as cur:
        cur.executemany(INSERT_SQL, rows)
        conn.commit()
    DAILY_ROWS[0] = len(rows)
    print(f"daily hk rows={len(rows)} date={today} universe={len(stocks)}")
    return 0


def run_daily_sina(threads: int = 6) -> int:
    """新浪口径港股日更：逐只抓全量日线后只写近 7 天 bfq（服务器可绕过腾讯 WAF）。"""
    today = datetime.now(CN).date()
    stocks = hk_universe()
    start = today - timedelta(days=10)
    written = {"n": 0}

    def worker(code: str) -> None:
        try:
            conn = db_conn()
            try:
                series = sina_series(code, "bfq", start, today)
                rows = [row for row in build_rows(conn, code, "bfq", series, source=SOURCE_SINA) if row[1] >= start]
                if rows:
                    with conn.cursor() as cur:
                        cur.executemany(INSERT_SQL, rows)
                    conn.commit()
                    with LOCK:
                        written["n"] += len(rows)
            finally:
                conn.close()
        except Exception:  # noqa: BLE001
            pass

    with ThreadPoolExecutor(max_workers=threads) as pool:
        futures = [pool.submit(worker, code) for code in stocks]
        for future in as_completed(futures):
            future.result()
    DAILY_ROWS[0] = written["n"]
    print(f"daily hk sina rows={written['n']} universe={len(stocks)} date={today}")
    return 0


def run_weekly(days: int, threads: int, source: str = "tencent") -> int:
    end = datetime.now(CN).date()
    start = end - timedelta(days=days)
    stocks = hk_universe()
    tasks = [(code, adjust) for code in stocks for adjust in ("bfq", "qfq", "hfq")]
    print(f"weekly hk tasks={len(tasks)} window={start}..{end}", flush=True)

    local = threading.local()

    def thread_conn() -> psycopg.Connection:
        conn = getattr(local, "conn", None)
        if conn is None or conn.closed:
            conn = db_conn()
            local.conn = conn
        return conn

    def worker(code: str, adjust: str):
        conn = thread_conn()
        session = requests.Session()
        session.headers.update(UA)
        try:
            if source == "sina":
                series = sina_series(code, adjust, start, end)
                rows = build_rows(conn, code, adjust, series, source=SOURCE_SINA)
            else:
                series = fetch_range(
                    session,
                    code,
                    adjust,
                    end,
                    stop_at=start,
                    count=max(80, days * 2),
                    floor=start,
                )
                rows = build_rows(conn, code, adjust, series)
            if rows:
                with conn.cursor() as cur:
                    cur.executemany(INSERT_SQL, rows)
                conn.commit()
        except Exception:  # noqa: BLE001
            pass

    with ThreadPoolExecutor(max_workers=threads) as pool:
        futures = [pool.submit(worker, code, adjust) for code, adjust in tasks]
        for future in as_completed(futures):
            try:
                future.result()
            except Exception:  # noqa: BLE001
                pass
    print("weekly hk done")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--mode", choices=["backfill", "daily", "weekly"], default="backfill")
    parser.add_argument("--codes", type=str, default="", help="逗号分隔，仅回填指定港股代码")
    parser.add_argument("--adjusts", type=str, default="bfq,qfq,hfq")
    parser.add_argument("--threads", type=int, default=8)
    parser.add_argument("--days", type=int, default=40)
    parser.add_argument("--end", type=str, default="", help="回填截止日 YYYY-MM-DD，默认今天")
    parser.add_argument("--years", type=int, default=6, help="回填历史年数（默认 6 年，对齐 A 股口径）")
    parser.add_argument("--full", action="store_true", help="从 1990 年起全量回填（慢，易触发 WAF）")
    parser.add_argument("--force", action="store_true")
    parser.add_argument(
        "--source",
        choices=["tencent", "sina", "auto"],
        default="auto",
        help="行情源：tencent（三口径 kline，易被 WAF）/ sina（新浪，服务器可用）",
    )
    args = parser.parse_args()
    codes = [item.strip().zfill(5) for item in args.codes.split(",") if item.strip()]
    adjusts = [item.strip() for item in args.adjusts.split(",") if item.strip()]
    end = date.fromisoformat(args.end) if args.end else datetime.now(CN).date()
    floor = date(1990, 1, 1) if args.full else end - timedelta(days=365 * args.years)
    if args.mode == "daily":
        if args.source == "sina":
            return run_daily_sina(args.threads)
        code = run_daily(args.threads)
        if args.source == "auto" and DAILY_ROWS[0] == 0:
            print("tencent qt empty, fallback to sina")
            return run_daily_sina(args.threads)
        return code
    if args.mode == "weekly":
        source = "sina" if args.source == "auto" else args.source
        return run_weekly(args.days, args.threads, source)
    source = "tencent" if args.source == "auto" else args.source
    return run_backfill(codes, adjusts, args.threads, args.force, end, floor, source)


if __name__ == "__main__":
    raise SystemExit(main())
