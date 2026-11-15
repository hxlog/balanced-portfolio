#!/usr/bin/env bash
cd /opt/balanced-portfolio
echo "--- 进程/日志 ---"
pgrep -fc xueqiu_quote_backfill || echo done
tail -3 /tmp/xueqiu_backfill3.log
echo "--- API 覆盖 ---"
curl -s --max-time 60 "http://127.0.0.1:8000/api/valuation/indices?limit=600" | .venv/bin/python -c "import sys,json; d=json.load(sys.stdin)['data']; f=lambda k: sum(1 for r in d if r.get(k) is not None); print('rows',len(d),'close',f('close_price'),'7d',f('change_7d_pct'),'52wH',f('high_52w'),'pos',f('position_52w_pct'))"
date