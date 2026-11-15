#!/usr/bin/env bash
set -uo pipefail
cd /opt/balanced-portfolio
echo "launch $(date +%H:%M:%S)"
setsid nohup nice -n 12 ionice -c2 -n7 .venv/bin/python scripts/csindex_quote_backfill.py > /tmp/csindex_quotes2.log 2>&1 < /dev/null &
sleep 45
grep -aE "index symbols|progress|WAF|budget|done" /tmp/csindex_quotes2.log | tail -6
echo "--- coverage ---"
su - postgres -c "psql -d postgres -tAc \"select count(distinct q.symbol) from bp_index_quote_daily q join bp_index_master m on m.index_code = q.symbol\""
free -h | head -2