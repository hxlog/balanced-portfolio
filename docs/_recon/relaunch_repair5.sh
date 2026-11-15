#!/usr/bin/env bash
set -uo pipefail
cd /opt/balanced-portfolio
pkill -f repair_stale_quotes || true
sleep 1
setsid nohup nice -n 12 ionice -c2 -n7 .venv/bin/python scripts/repair_stale_quotes.py > /tmp/repair_quotes6.log 2>&1 < /dev/null &
echo relaunched
