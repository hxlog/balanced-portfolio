import json, urllib.request
d = json.load(urllib.request.urlopen("http://127.0.0.1:8000/api/valuation/indices?limit=5", timeout=40))
rows = d.get("data") or []
print("rows:", len(rows))
for r in rows[:4]:
    print(r.get("index_code"), r.get("name"), "roe=", r.get("roe_ttm"), "fund_aum=", r.get("fund_aum"), "fund_count=", r.get("fund_count"))