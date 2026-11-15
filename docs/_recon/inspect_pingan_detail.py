# -*- coding: utf-8 -*-
"""检查平安指数详情原始字段（找 K 线 / 点位来源）。"""
import sys, json
sys.path.insert(0, "/opt/balanced-portfolio")
sys.stdout.reconfigure(encoding="utf-8")
from bp_ingest.valuation_pingan import fetch_index_detail
rows = fetch_index_detail(["ZI930641", "ZI000300"])
print("rows:", len(rows))
if rows:
    row = rows[0]
    print("keys:", sorted(row.keys()))
    print("sample:", json.dumps(row, ensure_ascii=False)[:1500])
