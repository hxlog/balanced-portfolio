#!/usr/bin/env bash
set -uo pipefail
cd /opt/balanced-portfolio
echo "start $(date +%H:%M:%S)"
BP_REQUEST_INTERVAL=0.4 BP_REQUEST_JITTER=0.6 setsid nohup bash -c '
  cd /opt/balanced-portfolio
  .venv/bin/python -m bp_ingest run --symbols $(tr "\n" " " < /tmp/valuation_symbols.txt)
  echo "ingest done $(date +%H:%M:%S)"
' > /tmp/valuation_backfill.log 2>&1 < /dev/null &
echo launched
sleep 20
tail -3 /tmp/valuation_backfill.log