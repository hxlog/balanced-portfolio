#!/usr/bin/env bash
set -uo pipefail
cd /opt/balanced-portfolio
setsid nohup nice -n 15 ionice -c2 -n7 .venv/bin/python /tmp/server_clean_indexes.py > /tmp/server_clean.log 2>&1 < /dev/null &
echo launched
sleep 20
tail -3 /tmp/server_clean.log
echo "--- backfill ---"
tail -2 /tmp/server_backfill.log | tr -d "\r" | tail -1
free -h | head -2