#!/usr/bin/env bash
cd /opt/balanced-portfolio
set -a
TOKEN=$(grep -m1 "^BP_INTERNAL_REVALIDATE_TOKEN=" .env | cut -d= -f2- | tr -d "\"\r ")
BP_INTERNAL_REVALIDATE_TOKEN="$TOKEN"
export BP_INTERNAL_REVALIDATE_TOKEN
set +a
echo "token len: ${#BP_INTERNAL_REVALIDATE_TOKEN}"
pm2 restart bp-web --update-env >/dev/null
sleep 6
echo "--- revalidate ---"
curl -s -X POST -H "X-Internal-Token: $BP_INTERNAL_REVALIDATE_TOKEN" http://127.0.0.1:3000/api/revalidate/valuation
echo
echo "--- page markers (cache-buster) ---"
curl -s "http://127.0.0.1:3000/valuation?nocache=$(date +%s)" | grep -oE "(上证指数|上证380|000001|示例数据|实时数据)" | sort | uniq -c