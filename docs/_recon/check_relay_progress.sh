#!/usr/bin/env bash
echo "--- relay backfill ---"
pgrep -fc csindex_quote_backfill || echo 0
grep -aE "progress|budget|done|WAF|fetch fail" /tmp/csindex_relay.log | tail -5
echo "--- API 覆盖 ---"
curl -s --max-time 60 "http://127.0.0.1:8000/api/valuation/indices?limit=600" | /opt/balanced-portfolio/.venv/bin/python -c "import sys,json; d=json.load(sys.stdin)['data']; f=lambda k: sum(1 for r in d if r.get(k) is not None); print('close',f('close_price'),'52wH',f('high_52w'),'7d',f('change_7d_pct'))"
echo "--- DB ---"
su - postgres -c "psql -d postgres -tAc \"select count(distinct q.symbol) from bp_index_quote_daily q join bp_index_master m on m.index_code = q.symbol\""
date