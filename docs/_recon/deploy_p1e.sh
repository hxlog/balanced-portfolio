#!/usr/bin/env bash
cd /opt/balanced-portfolio
git add -A bp_ingest/csindex_value.py bp_ingest/market_valuation.py
git -c user.name=deploy -c user.email=deploy@local commit -qm "P1: 中证官网日期解析修复；东财抓取节流" || true
echo "--- csindex rerun ---"
setsid nohup .venv/bin/python /tmp/run_csindex.py > /tmp/csindex2.log 2>&1 < /dev/null &
echo launched