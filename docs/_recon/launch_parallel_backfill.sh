#!/usr/bin/env bash
set -uo pipefail
echo '--- kill current backfill ---'
pkill -f 'bp_ingest run' || true
sleep 2
cd /opt/balanced-portfolio
.venv/bin/python /tmp/split_batches.py
echo '--- launch 4 parallel batches ---'
for i in 0 1 2 3; do
  BP_REQUEST_INTERVAL=0.15 BP_REQUEST_JITTER=0.25 setsid nohup .venv/bin/python -m bp_ingest run --no-clean --symbols $(tr '\n' ' ' < /tmp/vbatch_$i.txt) > /tmp/vbatch_$i.log 2>&1 < /dev/null &
done
echo launched