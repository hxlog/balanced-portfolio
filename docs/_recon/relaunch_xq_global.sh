#!/usr/bin/env bash
set -uo pipefail
cd /opt/balanced-portfolio
pkill -f xueqiu_quote_backfill || true
sleep 1
BP_XQ_BUDGET=900 setsid nohup nice -n 12 ionice -c2 -n7 .venv/bin/python scripts/xueqiu_quote_backfill.py > /tmp/xueqiu_backfill3.log 2>&1 < /dev/null &
sleep 50
grep -aE "targets|ok |skip|budget|done" /tmp/xueqiu_backfill3.log | tail -8
su - postgres -c "psql -d postgres -tAc \"select count(distinct q.symbol) from bp_index_quote_daily q join bp_index_master m on m.index_code = q.symbol\""