#!/usr/bin/env bash
set -uo pipefail
cd /opt/balanced-portfolio
git add -A bp_ingest/valuation_ingest.py
git -c user.name=deploy -c user.email=deploy@local commit -qm "P1: 修复跟踪基金 aum 解析" || true
setsid nohup .venv/bin/python -c "from bp_ingest.valuation_run import main; import sys; sys.exit(main())" > /tmp/valuation_ingest4.log 2>&1 < /dev/null &
echo relaunched