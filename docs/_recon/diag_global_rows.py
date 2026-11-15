# -*- coding: utf-8 -*-
import json, sys, urllib.request
sys.path.insert(0, "/opt/balanced-portfolio")
sys.stdout.reconfigure(encoding="utf-8")
from bp_ingest.config import load_config
from bp_ingest.db import connect

api = json.load(urllib.request.urlopen("http://127.0.0.1:8000/api/valuation/indices?limit=600", timeout=60))
rows = {r["index_code"]: r for r in api["data"]}
for code in ("标普500指数", "纳斯达克100指数", "恒生指数", "HSI"):
    r = rows.get(code)
    print(code, "in API:", bool(r), "close:", (r or {}).get("close_price"))
app = load_config()
with connect(app.db) as conn, conn.cursor() as cur:
    cur.execute("select symbol, count(*) from bp_index_quote_daily where source = %s group by 1 order by 2 desc limit 8", ("cn_index_xueqiu",))
    print("xueqiu symbols:", cur.fetchall())
    cur.execute("select count(*) from bp_index_quote_daily where source = %s", ("cn_index_xueqiu",))
    print("xueqiu rows:", cur.fetchone()[0])
