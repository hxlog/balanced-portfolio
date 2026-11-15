#!/usr/bin/env bash
set -uo pipefail
cd /opt/balanced-portfolio
TOKEN=$(grep -m1 "^BP_INTERNAL_REVALIDATE_TOKEN=" .env | cut -d= -f2- | tr -d "\r" | tr -d '"')
export BP_INTERNAL_REVALIDATE_TOKEN="$TOKEN"
echo "token len ${#TOKEN}"
pm2 restart bp-web --update-env >/dev/null
sleep 6
.venv/bin/python /tmp/trigger_revalidate.py || true
sleep 1
curl -s -o /dev/null -w "valuation:%{http_code} %{time_total}s\n" --max-time 40 http://127.0.0.1:3000/valuation