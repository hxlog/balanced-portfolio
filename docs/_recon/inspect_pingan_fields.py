# -*- coding: utf-8 -*-
"""检查平安指数行原始字段，寻找行情/点位数据。"""
import sys, json
sys.path.insert(0, "/opt/balanced-portfolio")
sys.stdout.reconfigure(encoding="utf-8")
from bp_ingest.valuation_pingan import fetch_index_universe
rows = fetch_index_universe()
print("rows:", len(rows))
row = rows[0]
print("keys:", sorted(row.keys()))
print("sample:", json.dumps({k: row[k] for k in list(row)[:40]}, ensure_ascii=False)[:1200])
