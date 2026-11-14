#!/usr/bin/env bash
cd /opt/balanced-portfolio
echo "--- live markers ---"
curl -s http://127.0.0.1:3000/valuation | grep -oE "(上证指数|上证380|000001|000009|示例数据|实时数据|中证中药)" | sort | uniq -c
echo "--- web env token ---"
mgrep -c BP_INTERNAL_REVALIDATE_TOKEN /proc/1/environ 2>/dev/null || true
pm2 env 1 2>/dev/null | grep -E "BP_INTERNAL_REVALIDATE_TOKEN|BP_API_BASE" | sed "s/=.*/=<set>/" || echo "no env output"