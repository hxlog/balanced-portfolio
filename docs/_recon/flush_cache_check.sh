#!/usr/bin/env bash
echo "--- redis keys ---"
redis-cli -h 127.0.0.1 -p 6379 --scan --pattern "*valuation*" 2>/dev/null | head -5
echo "--- flush valuation keys ---"
redis-cli -h 127.0.0.1 -p 6379 --scan --pattern "*valuation*" 2>/dev/null | while read -r k; do redis-cli -h 127.0.0.1 -p 6379 DEL "$k" >/dev/null; done
echo "--- API re-query ---"
cd /opt/balanced-portfolio
curl -s --max-time 60 "http://127.0.0.1:8000/api/valuation/indices?limit=600" | .venv/bin/python -c "import sys,json; d=json.load(sys.stdin)['data']; f=lambda k: sum(1 for r in d if r.get(k) is not None); print('rows',len(d),'close',f('close_price'),'7d',f('change_7d_pct'),'52wH',f('high_52w')); print([r['index_code'] for r in d if r.get('close_price') is None][:5])"