#!/usr/bin/env bash
set -uo pipefail
cd /opt/balanced-portfolio
setsid nohup nice -n 12 ionice -c2 -n7 .venv/bin/python scripts/csindex_oss_sync.py > /tmp/csindex_oss.log 2>&1 < /dev/null &
sleep 40
grep -aE "index symbols|progress|budget|done" /tmp/csindex_oss.log | tail -5
echo "--- coverage ---"
su - postgres -c "psql -d postgres -tAc \"select count(distinct q.symbol) from bp_index_quote_daily q join bp_index_master m on m.index_code = q.symbol\""
free -h | head -2