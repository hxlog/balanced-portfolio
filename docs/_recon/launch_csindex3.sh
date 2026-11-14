#!/usr/bin/env bash
cd /opt/balanced-portfolio
git add -A bp_ingest/csindex_value.py bp_ingest/stock_industry.py
git -c user.name=deploy -c user.email=deploy@local commit -qm "P1: 行业映射改申万；中证官网口径扩到全 A 股指数" || true
setsid nohup .venv/bin/python /tmp/run_csindex.py > /tmp/csindex3.log 2>&1 < /dev/null &
echo launched