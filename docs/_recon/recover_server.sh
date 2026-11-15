#!/usr/bin/env bash
for i in $(seq 1 30); do
  echo "[$i] $(date +%H:%M:%S) trying ssh..."
  if timeout 40 ssh -o BatchMode=yes -o ConnectTimeout=30 -o ServerAliveInterval=5 root@81.71.158.239 "echo connected; uptime" 2>&1; then
    echo "SSH OK at attempt $i"
    ssh -o BatchMode=yes -o ConnectTimeout=30 root@81.71.158.239 "pkill -f run_quote_batch12; pkill -f run_quote_batch; pkill -f cleanup_after_quote_backfill; sleep 3; echo killed; uptime; curl -s -o /dev/null -w \"api:%{http_code}\\n\" --max-time 10 http://127.0.0.1:8000/api/health" 2>&1
    break
  fi
  sleep 20
done