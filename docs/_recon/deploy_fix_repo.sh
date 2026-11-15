#!/usr/bin/env bash
set -uo pipefail
cd /opt/balanced-portfolio
.venv/bin/python -c "import bp_api.repositories_valuation; print('local import ok')" 2>&1 | tail -2
git add -A bp_api/repositories_valuation.py
git -c user.name=deploy -c user.email=deploy@local commit -qm "fix: rise_week/rise_year 回退字段（修正上版缩进错误）" || true
pm2 restart bp-api >/dev/null
sleep 6
curl -s -o /dev/null -w "health:%{http_code}\n" --max-time 10 http://127.0.0.1:8000/api/health
echo "--- indices sample ---"
curl -s --max-time 60 "http://127.0.0.1:8000/api/valuation/indices?limit=3" | head -c 300
echo
echo "--- coverage ---"
curl -s --max-time 60 "http://127.0.0.1:8000/api/valuation/indices?limit=600" | .venv/bin/python -c "import sys,json; d=json.load(sys.stdin)['data']; f=lambda k: sum(1 for r in d if r.get(k) is not None); print('rows',len(d),'| close',f('close_price'),'| 7d',f('change_7d_pct'),'| 52wRet',f('change_52w_pct'),'| pos',f('position_52w_pct'))"