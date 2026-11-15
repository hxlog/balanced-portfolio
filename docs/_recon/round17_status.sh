#!/usr/bin/env bash
echo "--- 回填进程 ---"
pgrep -af csindex_quote_backfill | head -2 || echo "已结束"
echo "--- 日志 ---"
grep -aE "progress|budget|done|WAF|fetch fail" /tmp/csindex_relay.log | tail -6
echo "--- API 覆盖 ---"
curl -s --max-time 60 "http://127.0.0.1:8000/api/valuation/indices?limit=600" | /opt/balanced-portfolio/.venv/bin/python -c "import sys,json; d=json.load(sys.stdin)['data']; f=lambda k: sum(1 for r in d if r.get(k) is not None); print('rows',len(d),'close',f('close_price'),'7d',f('change_7d_pct'),'52wH',f('high_52w'),'pos',f('position_52w_pct'))"
echo "--- 健康 ---"
curl -s -o /dev/null -w "web:%{http_code} api:" --max-time 10 http://127.0.0.1:3000/valuation
curl -s -o /dev/null -w "%{http_code}\n" --max-time 8 http://127.0.0.1:8000/api/health
date