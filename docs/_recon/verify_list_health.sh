#!/usr/bin/env bash
cd /opt/balanced-portfolio
pm2 restart bp-api >/dev/null
sleep 4
.venv/bin/python - <<'PY'
import json, urllib.request
d = json.load(urllib.request.urlopen("http://127.0.0.1:8000/api/valuation/indices?limit=3", timeout=40))
rows = d.get("data") or []
print("rows:", len(rows))
for r in rows[:2]:
    print({k: r.get(k) for k in ("index_code", "quote_status", "lag_trading_days", "fund_aum")})
PY
