#!/usr/bin/env bash
cd /opt/balanced-portfolio
git add -A bp_ingest/csindex_value.py
git -c user.name=deploy -c user.email=deploy@local commit -qm "P1: 中证官网第二口径源" || true
setsid nohup .venv/bin/python /tmp/run_csindex.py > /tmp/csindex.log 2>&1 < /dev/null &
echo launched