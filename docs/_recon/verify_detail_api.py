import json, urllib.request
for code in ("000300", "399986"):
    try:
        d = json.load(urllib.request.urlopen("http://127.0.0.1:8000/api/valuation/" + code, timeout=40))
    except Exception as exc:
        print(code, "FAIL", exc)
        continue
    data = d.get("data") or {}
    print(code, data.get("name"), "industry:", data.get("industry"), "intro:", (data.get("intro") or "")[:20])
    print("  percentiles:", len(data.get("percentiles") or []), "constituents:", len(data.get("constituents") or []), "funds:", len(data.get("tracker_funds") or []))
    risk = data.get("risk") or {}
    for key in ("1y", "3y", "5y"):
        if key in risk:
            r = risk[key]
            print("  risk", key, "annual:", r.get("annualized_return_pct"), "vol:", r.get("volatility_pct"), "mdd:", r.get("max_drawdown_pct"), "sharpe:", r.get("sharpe"))
