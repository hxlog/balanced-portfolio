#!/usr/bin/env bash
set -uo pipefail
pkill -f "bp_ingest run" 2>/dev/null || true
sleep 2
cd /opt/balanced-portfolio
for i in 0 1 2 3; do
  BP_REQUEST_INTERVAL=0.15 BP_REQUEST_JITTER=0.25 setsid nohup .venv/bin/python /tmp/run_quote_batch.py $i > /tmp/vbatch_$i.log 2>&1 < /dev/null &
done
sleep 20
echo "--- procs ---"
pgrep -fc run_quote_batch
for i in 0 1 2 3; do echo -n "batch$i: "; head -1 /tmp/vbatch_$i.log 2>/dev/null; done