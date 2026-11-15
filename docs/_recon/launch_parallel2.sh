#!/usr/bin/env bash
set -uo pipefail
cd /opt/balanced-portfolio
for i in 0 1 2 3; do
  BP_REQUEST_INTERVAL=0.15 BP_REQUEST_JITTER=0.25 setsid nohup bash -c ".venv/bin/python -m bp_ingest run --no-clean --symbols $(tr '\n' ' ' < /tmp/vbatch_$i.txt)" > /tmp/vbatch_$i.log 2>&1 < /dev/null &
done
sleep 15
echo "--- running procs ---"
pgrep -fc "bp_ingest run"
for i in 0 1 2 3; do echo "batch$i:"; tail -1 /tmp/vbatch_$i.log; done
date