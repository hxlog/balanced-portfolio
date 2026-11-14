#!/usr/bin/env bash
set -uo pipefail
cd /opt/balanced-portfolio
git add -A bp_api/quant/cleaning.py bp_ingest/sources.py
git -c user.name=deploy -c user.email=deploy@local commit -qm "P3: 清洗按主口径、bfq 映射修复" || true
timeout 300 .venv/bin/python /tmp/e2e_stock.py 2>&1 | tail -10