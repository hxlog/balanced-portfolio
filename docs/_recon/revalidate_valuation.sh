#!/usr/bin/env bash
set -uo pipefail
cd /opt/balanced-portfolio
TOKEN=$(grep -E "^BP_INTERNAL_REVALIDATE_TOKEN=" .env | cut -d= -f2- | tr -d '\r')
if [ -z "$TOKEN" ]; then echo "no token"; exit 1; fi
curl -s -X POST "http://127.0.0.1:3000/api/revalidate/valuation" -H "X-Internal-Token: $TOKEN" -H "Content-Type: application/json" -w "\nstatus:%{http_code}\n" | tail -3
curl -s -o /dev/null -w "detail:%{http_code}\n" --max-time 40 "http://127.0.0.1:3000/valuation/000300"
