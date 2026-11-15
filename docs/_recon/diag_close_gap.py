# -*- coding: utf-8 -*-
"""诊断：DB 有行情但 API close 为空的指数。"""
import json, sys, urllib.request
sys.path.insert(0, "/opt/balanced-portfolio")
sys.stdout.reconfigure(encoding="utf-8")
from bp_ingest.config import load_config
from bp_ingest.db import connect

api = json.load(urllib.request.urlopen("http://127.0.0.1:8000/api/valuation/indices?limit=600", timeout=60))
rows = api["data"]
null_close = [r["index_code"] for r in rows if r.get("close_price") is None]
print("api rows:", len(rows), "null close:", len(null_close))
app = load_config()
with connect(app.db) as conn, conn.cursor() as cur:
    for code in null_close[:5]:
        cur.execute("select source, adjust, count(*), max(trade_date) from bp_index_quote_daily where symbol = %s group by 1,2", (code,))
        print(code, "->", cur.fetchall())
    cur.execute("select distinct q.symbol from bp_index_quote_daily q join bp_index_master m on m.index_code = q.symbol")
    db_syms = {row[0] for row in cur.fetchall()}
api_syms = {r["index_code"] for r in rows if r.get("close_price") is not None}
print("db_only symbols:", sorted(db_syms - api_syms)[:10])
print("db_only count:", len(db_syms - api_syms))