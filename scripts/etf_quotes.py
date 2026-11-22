# -*- coding: utf-8 -*-
"""场内基金（ETF/LOF/封闭式）日线 ETL：腾讯行情 → bp_etf_quote_daily。

模式：
  --mode sync      同步场内基金列表（新浪基金行情分类）→ bp_etf_master
  --mode backfill  三口径历史回填（腾讯 fqkline，800/页，默认近 6 年）
  --mode daily     收盘后批量快照，仅写当日 bfq（腾讯 qt.gtimg.cn，60 只/请求）
  --mode weekly    近 N 天三口径增量（复权因子变化时刷新近端）

用法：
  python scripts/etf_quotes.py --mode sync
  python scripts/etf_quotes.py --mode backfill --threads 8
  python scripts/etf_quotes.py --mode daily
  python scripts/etf_quotes.py --mode weekly --days 40 --threads 8

口径：bfq 不复权（现价用）、qfq 前复权、hfq 后复权（腾讯口径=单位累计净值，
与东财 hfq 绝对值不同，仅收益率可比）。
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
NEWFQ = "https://ifzq.gtimg.cn/appstock/app/newfqkline/get"
NEWFQ_ALT = "https://proxy.finance.qq.com/ifzqgtimg/appstock/app/newfqkline/get"
SOURCE_KLINE = "tencent_etf_kline"
SOURCE_QT = "tencent_etf_qt"
SOURCE_SINA = "sina_etf_kline"
SOURCE_SINA_DAILY = "sina_etf_spot"
CN = timezone(timedelta(hours=8))
PAGE_SIZE = 800
SINA_CATEGORIES = {"ETF基金": "etf", "LOF基金": "lof", "封闭式基金": "closed"}
PROGRESS = {"ok": 0, "failed": 0, "rows": 0}
LOCK = threading.Lock()
FAILURES: list[str] = []
DAILY_ROWS = [0]  # 最近一次 daily 写入行数（auto 源降级判断用）
_MIN_INTERVAL = float(os.getenv("BP_ETF_MIN_INTERVAL", "0.05"))
_RATE_LOCK = threading.Lock()
_LAST_REQUEST = [0.0]


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


def throttled_get(session: requests.Session, url: str, **kwargs):
    with _RATE_LOCK:
        wait = _MIN_INTERVAL - (time.time() - _LAST_REQUEST[0])
        if wait > 0:
            time.sleep(wait)
        _LAST_REQUEST[0] = time.time()
    from bp_ingest.http_deadline import get_with_deadline

    return get_with_deadline(session, url, **kwargs)


def tx_symbol(code: str, market: str) -> str:
    prefix = (market or "").upper()
    if prefix == "SH" or (not prefix and code.startswith(("5", "6", "9"))):
        return "sh" + code
    return "sz" + code


def fetch_universe() -> list[tuple[str, str, str, str]]:
    """新浪基金行情分类 → [(etf_code, name, market, category)]。"""
    import akshare as ak

    out: list[tuple[str, str, str, str]] = []
    seen: set[str] = set()
    for category_name, category in SINA_CATEGORIES.items():
        df = ak.fund_etf_category_sina(symbol=category_name)
        for _, row in df.iterrows():
            raw = str(row["代码"]).strip().lower()
            if not raw or raw[:2] not in ("sh", "sz"):
                continue
            code = raw[2:].strip()
            if not (code.isdigit() and len(code) == 6) or code in seen:
                continue
            seen.add(code)
            out.append((code, str(row["名称"]).strip(), raw[:2].upper(), category))
    return out


def sync_master(universe: Sequence[tuple[str, str, str, str]]) -> int:
    with db_conn() as conn, conn.cursor() as cur:
        cur.executemany(
            "INSERT INTO bp_etf_master (etf_code, name, market, category, source, updated_at)"
            " VALUES (%s, %s, %s, %s, 'sina_fund_list', now())"
            " ON CONFLICT (etf_code) DO UPDATE SET name=EXCLUDED.name,"
            " market=EXCLUDED.market, category=EXCLUDED.category, updated_at=now()",
            list(universe),
        )
        conn.commit()
    return len(universe)


def universe_from_db(codes: Sequence[str] | None = None) -> list[tuple[str, str]]:
    with db_conn() as conn, conn.cursor() as cur:
        if codes:
            cur.execute(
                "SELECT etf_code, market FROM bp_etf_master WHERE etf_code = ANY(%s) ORDER BY etf_code",
                (list(codes),),
            )
        else:
            cur.execute("SELECT etf_code, market FROM bp_etf_master ORDER BY etf_code")
        return [(row[0], row[1] or "") for row in cur.fetchall()]


def sina_kline(code: str, market: str, start: date, end: date) -> list[tuple]:
    """新浪场内基金日线（不复权，全量返回后按区间过滤）。"""
    import akshare as ak

    symbol = (market or "SH").lower() + code
    try:
        df = ak.fund_etf_hist_sina(symbol=symbol)
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


def sina_spot_map() -> dict[str, dict]:
    """新浪基金行情分类快照：code -> {close, prev_close, open, high, low, volume, amount}。"""
    import akshare as ak

    out: dict[str, dict] = {}
    for category_name in SINA_CATEGORIES:
        try:
            df = ak.fund_etf_category_sina(symbol=category_name)
        except Exception:  # noqa: BLE001
            continue
        for _, row in df.iterrows():
            raw = str(row.get("代码") or "").strip().lower()
            if len(raw) < 8 or raw[:2] not in ("sh", "sz"):
                continue
            code = raw[2:]
            try:
                out[code] = {
                    "close": float(row["最新价"]),
                    "prev_close": float(row["昨收"]) if row.get("昨收") == row.get("昨收") else None,
                    "open": float(row["今开"]) if row.get("今开") == row.get("今开") else 0.0,
                    "high": float(row["最高"]) if row.get("最高") == row.get("最高") else 0.0,
                    "low": float(row["最低"]) if row.get("最低") == row.get("最低") else 0.0,
                    "volume": int(float(row["成交量"])) if row.get("成交量") == row.get("成交量") else 0,
                    "amount": float(row["成交额"]) if row.get("成交额") == row.get("成交额") else None,
                }
            except (TypeError, ValueError):
                continue
    return out


def parse_kline(rows: Iterable[Sequence]) -> list[tuple]:
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
                    # 腾讯 ETF kline 的 volume 单位是「手」（100 份），统一换算为「股」
                    int(float(row[5]) * 100),
                )
            )
        except (TypeError, ValueError, IndexError):
            continue
    return out


def fetch_page(session, code: str, market: str, adjust: str, end: date, count: int = PAGE_SIZE) -> list[tuple]:
    symbol = tx_symbol(code, market)
    kind = "" if adjust == "bfq" else adjust
    start = end - timedelta(days=365 * 10)
    param = f"{symbol},day,,{end.isoformat()},{count},{kind}"
    param_range = f"{symbol},day,{start.isoformat()},{end.isoformat()},{count},{kind}"
    key = {"bfq": "day", "qfq": "qfqday", "hfq": "hfqday"}[adjust]
    for url, param in (
        (KLINE_ALT, param),
        (NEWFQ_ALT, param_range),
        (NEWFQ, param_range),
        (KLINE, param),
    ):
        for attempt in range(2):
            try:
                response = throttled_get(session, url, params={"param": param}, timeout=20)
                response.raise_for_status()
                payload = response.json()
                data = (payload.get("data") or {}).get(symbol) or {}
                rows = data.get(key) or data.get("day") or []
                if rows:
                    return parse_kline(rows)
                break
            except Exception:  # noqa: BLE001
                time.sleep(1.0 * (attempt + 1))
    return []


def fetch_range(session, code: str, market: str, adjust: str, end: date, floor: date, stop_at: date | None = None) -> list[tuple]:
    rows: dict[date, tuple] = {}
    cursor = end
    while cursor >= floor:
        batch = fetch_page(session, code, market, adjust, cursor)
        if not batch:
            break
        for row in batch:
            rows[row[0]] = row
        first = min(row[0] for row in batch)
        if stop_at is not None and first <= stop_at:
            break
        if first <= floor or first >= cursor:
            break
        cursor = first - timedelta(days=1)
    return [rows[key] for key in sorted(rows)]


INSERT_SQL = (
    "INSERT INTO bp_etf_quote_daily"
    " (etf_code, trade_date, source, adjust, open, high, low, close, volume, pct_change)"
    " VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)"
    " ON CONFLICT (etf_code, trade_date, source, adjust) DO UPDATE SET"
    " open=EXCLUDED.open, high=EXCLUDED.high, low=EXCLUDED.low, close=EXCLUDED.close,"
    " volume=EXCLUDED.volume, pct_change=EXCLUDED.pct_change, captured_at=now()"
)


def previous_close(conn, code: str, adjust: str, before: date) -> float | None:
    with conn.cursor() as cur:
        cur.execute(
            "SELECT close FROM bp_etf_quote_daily WHERE etf_code=%s AND adjust=%s"
            " AND trade_date < %s ORDER BY trade_date DESC LIMIT 1",
            (code, adjust, before),
        )
        row = cur.fetchone()
    return float(row[0]) if row and row[0] is not None else None


def existing_range(conn, code: str, adjust: str) -> tuple[date | None, date | None, int]:
    with conn.cursor() as cur:
        cur.execute(
            "SELECT min(trade_date), max(trade_date), count(*) FROM bp_etf_quote_daily"
            " WHERE etf_code=%s AND adjust=%s AND source=%s",
            (code, adjust, SOURCE_KLINE),
        )
        row = cur.fetchone()
    return (row[0], row[1], int(row[2] or 0)) if row else (None, None, 0)


def build_rows(conn, code: str, adjust: str, series: list[tuple], source: str = SOURCE_KLINE) -> list[tuple]:
    if not series:
        return []
    dedup = {row[0]: row for row in series}
    ordered = [dedup[key] for key in sorted(dedup)]
    prev = previous_close(conn, code, adjust, ordered[0][0])
    out = []
    for trade_date, open_, high, low, close_, volume in ordered:
        pct = (close_ / prev - 1.0) * 100.0 if prev else None
        prev = close_
        out.append((code, trade_date, source, adjust, open_, high, low, close_, volume, pct))
    return out


def run_backfill(codes, years: int, threads: int, force: bool, end: date, source: str = "tencent", adjusts: list[str] | None = None) -> int:
    universe = universe_from_db(codes)
    if not universe:
        print("bp_etf_master 为空：先运行 --mode sync", flush=True)
        return 1
    floor = end - timedelta(days=365 * years)
    if adjusts is None:
        adjusts = ["bfq", "qfq", "hfq"] if source == "tencent" else ["bfq"]
    tasks = [(code, market, adjust) for code, market in universe for adjust in adjusts]
    print(f"backfill etf={len(universe)} tasks={len(tasks)} end={end} floor={floor}", flush=True)

    local = threading.local()

    def thread_conn():
        conn = getattr(local, "conn", None)
        if conn is None or conn.closed:
            conn = db_conn()
            local.conn = conn
        return conn

    def worker(code: str, market: str, adjust: str):
        conn = thread_conn()
        session = requests.Session()
        session.headers.update(UA)
        min_d, max_d, count = existing_range(conn, code, adjust)
        series: list[tuple] = []
        if source == "sina":
            series = sina_kline(code, market, floor, end)
            rows = build_rows(conn, code, adjust, series, source=SOURCE_SINA)
        else:
            if force or count == 0:
                series.extend(fetch_range(session, code, market, adjust, end, floor))
            else:
                series.extend(fetch_range(session, code, market, adjust, end, floor, stop_at=max_d))
                if min_d is not None and min_d > floor:
                    series.extend(
                        fetch_range(session, code, market, adjust, min_d - timedelta(days=1), floor)
                    )
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
            if total % 100 == 0:
                print(f"progress {total}/{len(tasks)} ok={PROGRESS['ok']} fail={PROGRESS['failed']} rows={PROGRESS['rows']}", flush=True)

    started = time.time()
    with ThreadPoolExecutor(max_workers=threads) as pool:
        futures = [pool.submit(worker, *task) for task in tasks]
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
        fail_path = os.path.join(log_dir, f"etf-failures-{end.isoformat()}.txt")
        with open(fail_path, "w", encoding="utf-8") as handle:
            handle.write("\n".join(FAILURES))
        print(f"failures written to {fail_path} ({len(FAILURES)})", flush=True)
    print(
        f"done ok={PROGRESS['ok']} failed={PROGRESS['failed']} rows={PROGRESS['rows']}"
        f" elapsed={int(time.time() - started)}s",
        flush=True,
    )
    return 0 if PROGRESS["failed"] == 0 else 1


def run_daily(source: str = "tencent") -> int:
    now = datetime.now(CN)
    if now.hour < 15 or (now.hour == 15 and now.minute < 10):
        print("skip: 收盘确认前（15:10 后运行）")
        return 0
    today = now.date()
    universe = universe_from_db()
    if source == "sina":
        spot = sina_spot_map()
        rows = []
        for code, _market in universe:
            item = spot.get(code)
            if not item or item["close"] is None or item["close"] <= 0:
                continue
            prev = item.get("prev_close")
            pct = ((item["close"] / prev - 1.0) * 100.0) if prev else None
            rows.append(
                (
                    code,
                    today,
                    SOURCE_SINA_DAILY,
                    "bfq",
                    item["open"],
                    item["high"],
                    item["low"],
                    item["close"],
                    item["volume"],
                    item["amount"],
                    pct,
                )
            )
        if rows:
            with db_conn() as conn, conn.cursor() as cur:
                cur.executemany(INSERT_SQL, rows)
                conn.commit()
        DAILY_ROWS[0] = len(rows)
        print(f"daily etf sina rows={len(rows)} date={today} universe={len(universe)}")
        return 0
    session = requests.Session()
    session.headers.update(UA)
    rows: list[tuple] = []
    for start in range(0, len(universe), 60):
        chunk = universe[start:start + 60]
        symbols = ",".join(tx_symbol(code, market) for code, market in chunk)
        try:
            response = throttled_get(session, QT + symbols, timeout=20)
            response.encoding = "gbk"
            text = response.text
        except Exception as exc:  # noqa: BLE001
            print("batch fail", start, type(exc).__name__)
            continue
        for line in text.split(";"):
            line = line.strip()
            if not line or "=" not in line:
                continue
            raw = line.split("=", 1)[1].strip().strip(chr(34))
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
                pct = float(parts[32]) if parts[32] else None
                stamp = parts[30]
                trade_date = date(int(stamp[0:4]), int(stamp[4:6]), int(stamp[6:8]))
            except (ValueError, IndexError):
                continue
            if trade_date != today or current <= 0:
                continue
            rows.append((code, trade_date, SOURCE_QT, "bfq", open_, high, low, current, volume, pct))
    if not rows:
        print(f"daily etf rows=0 date={today} universe={len(universe)}")
        return 0
    with db_conn() as conn, conn.cursor() as cur:
        cur.executemany(INSERT_SQL, rows)
        conn.commit()
    DAILY_ROWS[0] = len(rows)
    print(f"daily etf rows={len(rows)} date={today} universe={len(universe)}")
    return 0


def run_weekly(days: int, threads: int, source: str = "tencent") -> int:
    end = datetime.now(CN).date()
    start = end - timedelta(days=days)
    universe = universe_from_db()
    adjusts = ("bfq", "qfq", "hfq") if source == "tencent" else ("bfq",)
    tasks = [(code, market, adjust) for code, market in universe for adjust in adjusts]
    print(f"weekly etf tasks={len(tasks)} window={start}..{end}", flush=True)

    def worker(code: str, market: str, adjust: str):
        conn = db_conn()
        try:
            if source == "sina":
                series = sina_kline(code, market, start, end)
                rows = build_rows(conn, code, adjust, series, source=SOURCE_SINA)
            else:
                session = requests.Session()
                session.headers.update(UA)
                series = fetch_range(session, code, market, adjust, end, start, stop_at=start)
                rows = build_rows(conn, code, adjust, series)
            if rows:
                with conn.cursor() as cur:
                    cur.executemany(INSERT_SQL, rows)
                conn.commit()
        finally:
            conn.close()

    with ThreadPoolExecutor(max_workers=threads) as pool:
        futures = [pool.submit(worker, *task) for task in tasks]
        for future in as_completed(futures):
            try:
                future.result()
            except Exception:  # noqa: BLE001
                pass
    print("weekly etf done")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--mode", choices=["sync", "backfill", "daily", "weekly"], default="backfill")
    parser.add_argument("--codes", type=str, default="")
    parser.add_argument("--years", type=int, default=6)
    parser.add_argument("--days", type=int, default=40)
    parser.add_argument("--threads", type=int, default=8)
    parser.add_argument("--end", type=str, default="")
    parser.add_argument("--force", action="store_true")
    parser.add_argument("--adjusts", type=str, default="", help="逗号分隔，如 bfq,qfq,hfq；空=按 source 默认")
    parser.add_argument(
        "--source",
        choices=["tencent", "sina", "auto"],
        default="auto",
        help="行情源：tencent（三口径，易被 WAF）/ sina（新浪，服务器可用；仅 bfq）",
    )
    args = parser.parse_args()
    codes = [item.strip() for item in args.codes.split(",") if item.strip()]
    end = date.fromisoformat(args.end) if args.end else datetime.now(CN).date()
    if args.mode == "sync":
        universe = fetch_universe()
        total = sync_master(universe)
        print(f"etf master synced: {total}")
        return 0
    if args.mode == "daily":
        if args.source == "sina":
            return run_daily("sina")
        code = run_daily("tencent")
        if args.source == "auto" and DAILY_ROWS[0] == 0:
            print("tencent qt empty, fallback to sina")
            return run_daily("sina")
        return code
    if args.mode == "weekly":
        source = "sina" if args.source == "auto" else args.source
        return run_weekly(args.days, args.threads, source)
    source = "tencent" if args.source == "auto" else args.source
    adjust_list = [item.strip() for item in args.adjusts.split(",") if item.strip()] or None
    return run_backfill(codes, args.years, args.threads, args.force, end, source, adjust_list)


if __name__ == "__main__":
    raise SystemExit(main())
