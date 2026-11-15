# -*- coding: utf-8 -*-
p = "scripts/local_backfill_funds.py"
s = open(p, encoding="utf-8").read()
s = s.replace('''def write_fund(code: str, name: str, fund_type: str, nav_rows) -> int:
    is_etf = "ETF" in fund_type or "指数型" in fund_type
    with db_conn() as conn, conn.cursor() as cur:
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
        conn.commit()
    return len(payload)''',
'''def write_fund(code: str, name: str, fund_type: str, nav_rows) -> int:
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
    return len(payload)''')
s = s.replace('''LOCK = threading.Lock()
PROGRESS = {"ok": 0, "failed": 0, "rows": 0}''',
'''LOCK = threading.Lock()
PROGRESS = {"ok": 0, "failed": 0, "rows": 0}
local = threading.local()


def thread_conn():
    conn = getattr(local, "conn", None)
    if conn is None or conn.closed:
        conn = db_conn()
        local.conn = conn
        local.pending = 0
    return conn''')
s = s.replace("    parser.add_argument(\"--threads\", type=int, default=8)", "    parser.add_argument(\"--threads\", type=int, default=12)")
open(p, "w", encoding="utf-8").write(s)
print("fund patched:", "thread_conn" in s and "local.pending" in s)
