#!/usr/bin/env bash
set -uo pipefail
cd /opt/balanced-portfolio
pm2 restart bp-api >/dev/null
sleep 4
.venv/bin/python - <<'PY'
import json, urllib.request
c = json.load(urllib.request.urlopen("http://127.0.0.1:8000/api/valuation/funds/compare?codes=SH510300,SH510310,SH510330&benchmark=000300", timeout=60))
for item in c.get("items") or []:
    print(item.get("fund_code"), "ret", item.get("total_return_pct"), "te", item.get("tracking_error_pct"), "ir", item.get("info_ratio"), "excess", item.get("excess_return_pct"))
PY
