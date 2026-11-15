#!/usr/bin/env bash
set -uo pipefail
cd /opt/balanced-portfolio
echo "=== 页面耗时（3 次） ==="
for i in 1 2 3; do curl -s -o /dev/null -w "  run$i: %{http_code} %{time_total}s\n" --max-time 40 "http://127.0.0.1:3000/valuation"; done
echo "=== API 耗时 ==="
for q in "indices?limit=1000&window=5y&metric=pe_ttm" "indices?limit=1000&window=1y&metric=pb" "indices?limit=1000&industry=%E9%93%B6%E8%A1%8C" "overview?window=1y"; do
  curl -s -o /dev/null -w "  $q -> %{http_code} %{time_total}s\n" --max-time 60 "http://127.0.0.1:8000/api/valuation/$q"
done
echo "=== 页面 200 + 关键文本 ==="
curl -s --max-time 40 http://127.0.0.1:3000/valuation | grep -oE "代表性宽基估值|PE-Band|行业估值热力|估值矩阵|全市场截面|指数列表|1 年|全历史" | sort | uniq -c
