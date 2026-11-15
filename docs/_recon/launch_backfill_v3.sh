#!/usr/bin/env bash
set -uo pipefail
pkill -f server_quote_backfill2.py || true
sleep 2
cd /opt/balanced-portfolio
setsid nohup nice -n 10 ionice -c2 -n7 .venv/bin/python /tmp/server_quote_backfill3.py > /tmp/server_backfill3.log 2>&1 < /dev/null &
echo launched
sleep 40
grep -a "missing\|progress" /tmp/server_backfill3.log | tail -3
free -h | head -2