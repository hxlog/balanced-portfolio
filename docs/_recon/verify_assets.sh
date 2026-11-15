#!/usr/bin/env bash
cd /opt/balanced-portfolio
.venv/bin/python - <<'PY'
import json, urllib.request
for path in ("/api/assets/unified?q=600519&limit=5", "/api/assets/unified?type=index&limit=2", "/api/assets/unified?type=fund&q=005827&limit=2"):
    d = json.load(urllib.request.urlopen("http://127.0.0.1:8000" + path, timeout=60))
    rows = d.get("data") or []
    print(path.split("?")[1][:30], "rows:", len(rows), "total:", (d.get("meta") or {}).get("total"))
    for row in rows[:2]:
        print("  ", row["type"], row["code"], row["name"], row["last_date"])
PY
su - postgres -c "psql -d postgres -tAc \"select adjust, count(*), count(distinct symbol), max(trade_date) from bp_stock_quote_daily group by 1\""
su - postgres -c "psql -d postgres -tAc \"select count(distinct fund_code), count(*) from bp_fund_nav_daily\""
