#!/usr/bin/env bash
set -uo pipefail
cd /opt/balanced-portfolio
pkill -f "backfill_fund_data.*--fees" || true
sleep 1
setsid nohup nice -n 12 ionice -c2 -n7 .venv/bin/python scripts/backfill_fund_data.py --fees > /tmp/fund_fees2.log 2>&1 < /dev/null &
echo launched
sleep 30
tail -4 /tmp/fund_fees2.log
su - postgres -c "psql -d postgres -tAc \"select count(*) filter (where management_fee is not null), count(*) filter (where established_date is not null), count(*) filter (where fund_scale is not null) from bp_fund_master\""
echo "=== 健康看护 ==="
pgrep -fc quote_coverage_watch || echo "health done"
tail -4 /tmp/quote_health.log 2>/dev/null
