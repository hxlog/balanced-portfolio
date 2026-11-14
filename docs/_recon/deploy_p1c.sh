#!/usr/bin/env bash
cd /opt/balanced-portfolio
echo "--- csindex progress ---"
ps aux | grep -c "[r]un_csindex"
tail -2 /tmp/csindex.log 2>/dev/null || echo "no log"
echo "--- industry sync ---"
timeout 180 .venv/bin/python /tmp/run_industry.py 2>&1 | tail -3
echo "--- deploy scheduler ---"
git add -A bp_ingest/scheduler.py bp_ingest/market_valuation.py bp_ingest/stock_industry.py
git -c user.name=deploy -c user.email=deploy@local commit -qm "P1: 调度挂载全市场估值/中证官网口径；行业映射模块" || true
pm2 restart bp-ingest bp-beat >/dev/null
echo done