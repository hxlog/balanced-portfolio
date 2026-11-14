#!/usr/bin/env bash
cd /opt/balanced-portfolio
echo "--- API sample ---"
curl -s "http://127.0.0.1:8000/api/valuation/indices?limit=3" | head -c 700
echo
echo "--- overview ---"
curl -s "http://127.0.0.1:8000/api/valuation/overview" | head -c 300
echo
echo "--- revalidate ---"
TOKEN=$(grep -m1 "^BP_INTERNAL_REVALIDATE_TOKEN=" .env | cut -d= -f2- | tr -d "\"\r ")
curl -s -X POST -H "X-Internal-Token: $TOKEN" http://127.0.0.1:3000/api/revalidate/valuation
echo
echo "--- page check ---"
curl -s http://127.0.0.1:3000/valuation | grep -oE "(中证中药|沪深300|风险溢价|指数估值|示例数据)" | sort | uniq -c