#!/usr/bin/env bash
set -uo pipefail
cd /opt/balanced-portfolio
pm2 restart bp-api >/dev/null
sleep 5
.venv/bin/python /tmp/trigger_revalidate.py || true
sleep 2
echo "=== overview proxies ==="
curl -s --max-time 40 "http://127.0.0.1:8000/api/valuation/overview?window=5y" | .venv/bin/python -c "
import json,sys
d=json.load(sys.stdin)
meta=d.get('meta') or {}
print('boards:', len(d.get('data') or []))
for p in (meta.get('proxies') or []):
    print(' ', p.get('index_code'), p.get('name'), 'PE', p.get('pe_ttm'), 'PEpct', p.get('pe_percentile'), 'PBpct', p.get('pb_percentile'))
"
echo "=== page markers ==="
curl -s -o /tmp/val.html -w "valuation:%{http_code} %{time_total}s\n" --max-time 40 http://127.0.0.1:3000/valuation
grep -oE "代表性宽基估值|行业估值热力|估值矩阵|全市场截面|指数列表|PE-Band" /tmp/val.html | sort | uniq -c
