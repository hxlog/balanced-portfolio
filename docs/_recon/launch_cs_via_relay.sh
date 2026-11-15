#!/usr/bin/env bash
set -uo pipefail
cd /opt/balanced-portfolio
pkill -f csindex_drip || true
pkill -f csindex_quote_backfill || true
sleep 1
export HTTPS_PROXY=http://127.0.0.1:10809
export HTTP_PROXY=http://127.0.0.1:10809
export NO_PROXY=127.0.0.1,localhost,81.71.158.239
setsid nohup nice -n 12 ionice -c2 -n7 .venv/bin/python scripts/csindex_quote_backfill.py > /tmp/csindex_relay.log 2>&1 < /dev/null &
echo launched
sleep 60
grep -aE "index symbols|progress|WAF|budget|done" /tmp/csindex_relay.log | tail -5
echo "--- coverage ---"
su - postgres -c "psql -d postgres -tAc \"select count(distinct q.symbol) from bp_index_quote_daily q join bp_index_master m on m.index_code = q.symbol\""