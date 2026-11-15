#!/usr/bin/env bash
set -uo pipefail
cd /opt/balanced-portfolio
pm2 restart bp-web >/dev/null
sleep 6
TOKEN=$(grep -m1 "^BP_INTERNAL_REVALIDATE_TOKEN=" .env | cut -d= -f2- | tr -d "\"\r ")
curl -s -X POST -H "X-Internal-Token: $TOKEN" http://127.0.0.1:3000/api/revalidate/valuation > /dev/null || true
sleep 2
curl -s -o /dev/null -w "valuation:%{http_code} " --max-time 15 http://127.0.0.1:3000/valuation
curl -s -o /dev/null -w "detail:%{http_code}\n" --max-time 15 http://127.0.0.1:3000/valuation/930641
echo "--- markers ---"
curl -s --max-time 20 http://127.0.0.1:3000/valuation | grep -oE "52 周位置|年涨幅|Mock|示例数据" | sort | uniq -c