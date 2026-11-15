#!/usr/bin/env bash
cd /opt/balanced-portfolio
curl -s "http://127.0.0.1:8000/api/valuation/indices?limit=600" | .venv/bin/python -c "import sys,json; d=json.load(sys.stdin)['data']; n=len(d); f=lambda k: sum(1 for r in d if r.get(k) is not None); print('rows',n,'| pe',f('pe_ttm'),'| pct',f('pe_percentile'),'| close',f('close_price'),'| 7d',f('change_7d_pct'),'| 52w',f('high_52w'))"
tail -2 /tmp/server_backfill.log | tr -d "\r" | tail -1
free -h | head -2