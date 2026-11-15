# -*- coding: utf-8 -*-
p = "scripts/local_backfill_stocks.py"
s = open(p, encoding="utf-8").read()
start = s.index("    def worker(code: str, market: str, missing):")
end = s.index("    started = time.time()")
new_worker = '''    local = threading.local()

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

'''
s = s[:start] + new_worker + s[end:]
open(p, "w", encoding="utf-8").write(s)
print("patched thread-local:", "thread_conn" in s and "local.pending" in s)
