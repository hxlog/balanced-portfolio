#!/usr/bin/env bash
set -uo pipefail
cd /opt/balanced-portfolio
echo "launch $(date +%H:%M:%S)"
setsid nohup nice -n 10 ionice -c2 -n7 .venv/bin/python /tmp/server_quote_backfill.py > /tmp/server_backfill.log 2>&1 < /dev/null &
echo launched
sleep 30
tail -3 /tmp/server_backfill.log
free -h | head -2