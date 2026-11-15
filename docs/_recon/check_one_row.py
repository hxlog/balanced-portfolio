# -*- coding: utf-8 -*-
import json, sys, urllib.request
sys.stdout.reconfigure(encoding="utf-8")
api = json.load(urllib.request.urlopen("http://127.0.0.1:8000/api/valuation/indices?limit=600", timeout=60))
rows = api["data"]
lookup = {r["index_code"]: r for r in rows}
for code in ("930598", "930601", "930604", "000300", "930641"):
    r = lookup.get(code)
    if r is None:
        print(code, "NOT IN API ROWS")
    else:
        print(code, "close=", r.get("close_price"), "5d=", r.get("change_7d_pct"), "52w=", r.get("high_52w"), "trade_date=", r.get("trade_date"))
