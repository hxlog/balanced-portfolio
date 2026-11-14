#!/usr/bin/env bash
set -uo pipefail
cd /opt/balanced-portfolio
TOKEN=$(grep -m1 '^BP_INTERNAL_REVALIDATE_TOKEN=' .env | cut -d= -f2- | tr -d '\"\r ')
echo '--- revalidate ---'
curl -s -X POST -H "X-Internal-Token: $TOKEN" http://127.0.0.1:3000/api/revalidate/valuation
echo
sleep 2
echo '--- page markers ---'
curl -s http://127.0.0.1:3000/valuation | grep -oE 'Mock 示例|尚未接入 API|上证指数|中证中药|521 只指数' | sort | uniq -c
echo '--- page timing ---'
curl -s -o /dev/null -w 'page:%{http_code} %{time_total}s\n' http://127.0.0.1:3000/valuation