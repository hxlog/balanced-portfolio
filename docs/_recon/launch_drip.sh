#!/usr/bin/env bash
set -uo pipefail
cd /opt/balanced-portfolio
pkill -f csindex_quote_backfill || true
setsid nohup nice -n 12 ionice -c2 -n7 .venv/bin/python scripts/csindex_drip.py > /tmp/csindex_drip.log 2>&1 < /dev/null &
echo "launched drip"
sleep 60
grep -aE "missing|ok |403 backoff|done|fail" /tmp/csindex_drip.log | tail -6
echo "--- coverage ---"
su - postgres -c "psql -d postgres -tAc \"select count(distinct q.symbol) from bp_index_quote_daily q join bp_index_master m on m.index_code = q.symbol\""