#!/usr/bin/env bash
cd /opt/balanced-portfolio
for i in 1 2; do curl -s -o /dev/null -w "run$i: %{http_code} %{time_total}s\n" --max-time 60 "http://127.0.0.1:8000/api/valuation/indices?limit=600"; done
curl -s --max-time 60 "http://127.0.0.1:8000/api/valuation/indices?limit=600" | .venv/bin/python -c "import sys,json; d=json.load(sys.stdin)['data']; f=lambda k: sum(1 for r in d if r.get(k) is not None); print('rows',len(d),'close',f('close_price'),'7d',f('change_7d_pct'),'52w',f('high_52w'),'pos',f('position_52w_pct'))"
echo "--- backfill/clean ---"
grep -a "progress" /tmp/server_backfill.log | tail -2
tail -1 /tmp/server_clean.log
free -h | head -2