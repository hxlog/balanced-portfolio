#!/usr/bin/env bash
cd /opt/balanced-portfolio
echo "--- health ---"
curl -s -o /dev/null -w "%{http_code}\n" --max-time 10 http://127.0.0.1:8000/api/health
echo "--- indices response ---"
curl -s --max-time 60 "http://127.0.0.1:8000/api/valuation/indices?limit=3" | head -c 400
echo
echo "--- api log tail ---"
tail -15 /root/.pm2/logs/bp-api-error.log 2>/dev/null | grep -iE "error|exception|syntax" | tail -5