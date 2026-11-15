#!/usr/bin/env bash
cd /opt/balanced-portfolio
echo "=== pm2 status ==="
pm2 list | grep -E "bp-api|bp-web" || true
echo "=== api error log tail ==="
tail -25 /root/.pm2/logs/bp-api-error.log | tail -18
echo "=== assets files ==="
ls web/app/assets/ 2>/dev/null || echo missing
echo "=== api health ==="
curl -s -o /dev/null -w "health:%{http_code}\n" --max-time 10 http://127.0.0.1:8000/api/health
