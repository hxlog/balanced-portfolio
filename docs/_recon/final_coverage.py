# -*- coding: utf-8 -*-
import json, sys, urllib.request
sys.stdout.reconfigure(encoding="utf-8")
api = json.load(urllib.request.urlopen("http://127.0.0.1:8000/api/valuation/indices?limit=600", timeout=60))
rows = api["data"]
f = lambda k: sum(1 for r in rows if r.get(k) is not None)
print("rows", len(rows))
for k in ("pe_ttm","pb","dividend_yield_ttm","erp","pe_percentile","pb_percentile","close_price","change_pct","change_7d_pct","change_52w_pct","high_52w","position_52w_pct"):
    print("  %-18s %d" % (k, f(k)))
