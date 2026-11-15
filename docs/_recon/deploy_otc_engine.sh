#!/usr/bin/env bash
set -uo pipefail
cd /opt/balanced-portfolio
pm2 restart bp-api >/dev/null
sleep 4
curl -s -o /dev/null -w "api:%{http_code}\n" --max-time 10 http://127.0.0.1:8000/api/health
