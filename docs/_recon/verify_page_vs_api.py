# -*- coding: utf-8 -*-
"""核对：线上页面渲染值 vs API 返回值的抽样一致性。"""
import re, sys, json, urllib.request
sys.stdout.reconfigure(encoding="utf-8")
API = "http://127.0.0.1:8000/api/valuation/indices?limit=600"
PAGE = "http://127.0.0.1:3000/valuation"
api = json.load(urllib.request.urlopen(API, timeout=30))
rows = api["data"]
print("api rows:", len(rows), "meta:", {k: api["meta"].get(k) for k in ("rows", "as_of")})
by_code = {r["index_code"]: r for r in rows}
html = urllib.request.urlopen(PAGE, timeout=30).read().decode("utf-8", "ignore")
print("page bytes:", len(html))
print("mock markers:", [m for m in ("Mock 示例", "示例数据", "尚未接入 API") if m in html])
checks = []
for code in ("000001", "000300", "000905", "930641", "399006"):
    r = by_code.get(code)
    if not r:
        continue
    pe = r.get("pe_ttm")
    name = r.get("name")
    # 页面里应出现该指数名与 PE 两位小数值
    pe_str = f"{pe:.2f}" if isinstance(pe, (int, float)) else None
    checks.append((code, name, pe_str, name in html, (pe_str in html) if pe_str else None, r.get("close_price"), r.get("pe_percentile")))
for c in checks:
    print("  ", c)
print("--- 非空率 ---")
for field in ("pe_ttm", "pb", "dividend_yield_ttm", "erp", "close_price", "change_pct", "pe_percentile", "pb_percentile"):
    nonnull = sum(1 for r in rows if r.get(field) is not None)
    print(f"  {field}: {nonnull}/{len(rows)}")
