#!/usr/bin/env bash
set -uo pipefail
cd /opt/balanced-portfolio
git add -A bp_api/repositories_valuation.py
git -c user.name=deploy -c user.email=deploy@local commit -qm "feat: 指标列表增加 7 日涨跌与 52 周高低/位置字段" || true
pm2 restart bp-api >/dev/null
sleep 4
echo "--- timing ---"
for i in 1 2; do curl -s -o /dev/null -w "run$i: %{http_code} %{time_total}s\n" "http://127.0.0.1:8000/api/valuation/indices?limit=600"; done
echo "--- fields sample ---"
curl -s "http://127.0.0.1:8000/api/valuation/indices?limit=3" | .venv/bin/python -c "import sys,json; d=json.load(sys.stdin)['data']; [print({k: r.get(k) for k in ('index_code','close_price','change_pct','change_7d_pct','high_52w','low_52w','position_52w_pct')}) for r in d]"
echo "--- backfill progress ---"
tail -2 /tmp/valuation_backfill.log