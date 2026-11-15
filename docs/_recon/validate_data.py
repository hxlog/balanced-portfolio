# -*- coding: utf-8 -*-
"""数据有效性/一致性校验（生产）。"""
import json, sys, urllib.request
sys.stdout.reconfigure(encoding="utf-8")
API = "http://127.0.0.1:8000/api/valuation/indices?limit=600"
d = json.load(urllib.request.urlopen(API, timeout=60))
rows = d["data"]
print("rows:", len(rows))
bad = 0
for r in rows:
    pe, pb, pct = r.get("pe_ttm"), r.get("pb"), r.get("pe_percentile")
    if pe is not None and not (0 < pe < 2000): bad += 1; print("bad pe", r["index_code"], pe)
    if pb is not None and not (0 < pb < 500): bad += 1; print("bad pb", r["index_code"], pb)
    if pct is not None and not (0 <= pct <= 100): bad += 1; print("bad pct", r["index_code"], pct)
    pos, hi, lo, close = r.get("position_52w_pct"), r.get("high_52w"), r.get("low_52w"), r.get("close_price")
    if None not in (pos, hi, lo, close) and hi > lo:
        expect = (close - lo) / (hi - lo) * 100
        if abs(expect - pos) > 0.01:
            bad += 1; print("pos mismatch", r["index_code"], pos, expect)
    if None not in (hi, lo, close) and not (lo - 1e-6 <= close <= hi + 1e-6):
        bad += 1; print("close out of 52w range", r["index_code"], close, lo, hi)
print("checks bad:", bad)
print("--- 有效性汇总 ---")
f = lambda k: sum(1 for r in rows if r.get(k) is not None)
for k in ("pe_ttm", "pb", "dividend_yield_ttm", "erp", "pe_percentile", "pb_percentile", "close_price", "change_pct", "change_7d_pct", "change_52w_pct", "high_52w", "position_52w_pct"):
    print("  %-18s %d/%d" % (k, f(k), len(rows)))
