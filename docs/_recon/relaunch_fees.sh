#!/usr/bin/env bash
set -uo pipefail
cd /opt/balanced-portfolio
echo "=== 重跑基金费率回填（后台） ==="
setsid nohup nice -n 12 ionice -c2 -n7 .venv/bin/python scripts/backfill_fund_data.py --fees > /tmp/fund_fees.log 2>&1 < /dev/null &
echo launched
sleep 25
tail -4 /tmp/fund_fees.log
echo "=== 行情健康看护 ==="
pgrep -fc quote_coverage_watch || echo "health done"
tail -8 /tmp/quote_health.log 2>/dev/null
