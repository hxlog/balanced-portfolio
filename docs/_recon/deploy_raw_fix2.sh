#!/usr/bin/env bash
set -uo pipefail
cd /opt/balanced-portfolio
git add -A bp_api/repositories_valuation.py
git -c user.name=deploy -c user.email=deploy@local commit -qm "fix: 估值页行情 LATERAL 改回原始行情表（此前误保留清洗表）" || true
pm2 restart bp-api >/dev/null
sleep 5
redis-cli -h 127.0.0.1 -p 6379 --scan --pattern "*valuation*" 2>/dev/null | while read -r k; do redis-cli -h 127.0.0.1 -p 6379 DEL "$k" >/dev/null; done
curl -s --max-time 60 "http://127.0.0.1:8000/api/valuation/indices?limit=600" | .venv/bin/python -c "import sys,json; d=json.load(sys.stdin)['data']; f=lambda k: sum(1 for r in d if r.get(k) is not None); print('rows',len(d),'close',f('close_price'),'7d',f('change_7d_pct'),'52wH',f('high_52w'),'pos',f('position_52w_pct'))"