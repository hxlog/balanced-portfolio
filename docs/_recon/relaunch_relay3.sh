#!/usr/bin/env bash
set -uo pipefail
cd /opt/balanced-portfolio
pkill -f csindex_quote_backfill || true
sleep 1
BP_HTTP_PROXY=http://127.0.0.1:10809 setsid nohup nice -n 12 ionice -c2 -n7 .venv/bin/python scripts/csindex_quote_backfill.py > /tmp/csindex_relay3.log 2>&1 < /dev/null &
echo launched
sleep 75
grep -aE "index symbols|progress|skip-invalid|WAF|budget|done|fetch fail" /tmp/csindex_relay3.log | tail -6
echo "--- API ---"
curl -s --max-time 60 "http://127.0.0.1:8000/api/valuation/indices?limit=600" | .venv/bin/python -c "import sys,json; d=json.load(sys.stdin)['data']; f=lambda k: sum(1 for r in d if r.get(k) is not None); print('close',f('close_price'),'52wH',f('high_52w'))"
su - postgres -c "psql -d postgres -tAc \"select count(distinct q.symbol) from bp_index_quote_daily q join bp_index_master m on m.index_code = q.symbol\""