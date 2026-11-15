#!/usr/bin/env bash
set -uo pipefail
pkill -f run_quote_batch 2>/dev/null || true
sleep 2
cd /opt/balanced-portfolio
.venv/bin/python /tmp/split12.py
for i in $(seq 0 11); do
  BP_MAX_RETRIES=1 BP_REQUEST_INTERVAL=0.1 BP_REQUEST_JITTER=0.2 setsid nohup .venv/bin/python /tmp/run_quote_batch12.py $i > /tmp/vb12_$i.log 2>&1 < /dev/null &
done
sleep 15
echo "procs: $(pgrep -fc run_quote_batch12 || echo 0)"
date