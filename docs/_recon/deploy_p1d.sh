#!/usr/bin/env bash
cd /opt/balanced-portfolio
git add -A bp_ingest/csindex_value.py bp_ingest/stock_industry.py
git -c user.name=deploy -c user.email=deploy@local commit -qm "P1: 差异日志按序列对齐；行业抓取节流" || true
echo "--- diff ---"
.venv/bin/python /tmp/run_diff.py 2>&1 | tail -3
echo "--- industry retry ---"
timeout 150 .venv/bin/python /tmp/run_industry.py 2>&1 | tail -3