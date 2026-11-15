#!/usr/bin/env bash
set -uo pipefail
cd /opt/balanced-portfolio
pm2 restart bp-web >/dev/null
sleep 6
TOKEN=$(grep -m1 '^BP_INTERNAL_REVALIDATE_TOKEN=' .env | cut -d= -f2- | tr -d '\"\r ')
curl -s -X POST -H "X-Internal-Token: $TOKEN" http://127.0.0.1:3000/api/revalidate/valuation > /dev/null || true
sleep 2
echo '--- markers ---'
curl -s http://127.0.0.1:3000/valuation | grep -oE '52 周位置|Mock|示例数据|上证指数' | sort | uniq -c
echo '--- api coverage ---'
curl -s 'http://127.0.0.1:8000/api/valuation/indices?limit=600' | .venv/bin/python -c "import sys,json; d=json.load(sys.stdin)['data']; n=len(d); f=lambda k: sum(1 for r in d if r.get(k) is not None); print('rows',n,'close',f('close_price'),'7d',f('change_7d_pct'),'52wHigh',f('high_52w'),'pos',f('position_52w_pct'))"