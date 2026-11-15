#!/usr/bin/env bash
set -uo pipefail
cd /opt/balanced-portfolio
pm2 restart bp-web >/dev/null
sleep 6
TOKEN=$(grep -m1 '^BP_INTERNAL_REVALIDATE_TOKEN=' .env | cut -d= -f2- | tr -d '\"\r ')
curl -s -X POST -H "X-Internal-Token: $TOKEN" http://127.0.0.1:3000/api/revalidate/valuation > /dev/null || true
sleep 2
echo '--- 页面标记 ---'
curl -s http://127.0.0.1:3000/valuation | grep -oE 'Mock 示例|示例数据|尚未接入 API|上证指数|PE 分位|521 只指数' | sort | uniq -c
echo '--- 页面时间 ---'
curl -s -o /dev/null -w 'valuation:%{http_code} %{time_total}s\n' http://127.0.0.1:3000/valuation
curl -s -o /dev/null -w 'detail:%{http_code}\n' http://127.0.0.1:3000/valuation/930641
curl -s -o /dev/null -w 'builder:%{http_code}\n' http://127.0.0.1:3000/builder