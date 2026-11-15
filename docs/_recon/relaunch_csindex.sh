#!/usr/bin/env bash
set -uo pipefail
cd /opt/balanced-portfolio
pkill -f csindex_quote_backfill || true
sleep 1
setsid nohup nice -n 12 ionice -c2 -n7 .venv/bin/python scripts/csindex_quote_backfill.py > /tmp/csindex_quotes.log 2>&1 < /dev/null &
echo launched
sleep 45
tail -5 /tmp/csindex_quotes.log
echo "--- coverage ---"
su - postgres -c "psql -d postgres -tAc \"select count(distinct q.symbol) from bp_index_quote_daily q join bp_index_master m on m.index_code = q.symbol\""
free -h | head -2