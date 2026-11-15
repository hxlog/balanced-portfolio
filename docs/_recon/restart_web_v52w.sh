#!/usr/bin/env bash
set -uo pipefail
cd /opt/balanced-portfolio
pm2 restart bp-web >/dev/null
sleep 5
TOKEN=$(grep -m1 "^BP_INTERNAL_REVALIDATE_TOKEN=" .env | cut -d= -f2- | tr -d "\"\r ")
curl -s -X POST -H "X-Internal-Token: $TOKEN" http://127.0.0.1:3000/api/revalidate/valuation > /dev/null || true
echo "web restarted"
curl -s http://127.0.0.1:3000/valuation | grep -o "周位置" | head -1