import json, urllib.request
d = json.load(urllib.request.urlopen("http://127.0.0.1:8000/api/valuation/overview?window=5y", timeout=40))
meta = d.get("meta") or {}
proxies = meta.get("proxies") or []
print("proxy count:", len(proxies))
for p in proxies:
    print(" ", p.get("index_code"), p.get("name"), "PE", p.get("pe_ttm"), "PEpct", p.get("pe_percentile"))