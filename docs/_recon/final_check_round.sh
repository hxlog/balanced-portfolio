#!/usr/bin/env bash
cd /opt/balanced-portfolio
curl -s http://127.0.0.1:3000/valuation -o /tmp/valf.html
echo "page bytes: $(wc -c < /tmp/valf.html)"
for m in "52 周位置" "Mock" "示例数据" "上证指数"; do printf "%-12s %s\n" "$m" "$(grep -o "$m" /tmp/valf.html | wc -l)"; done
curl -s "http://127.0.0.1:8000/api/valuation/indices?limit=600" | .venv/bin/python -c "import sys,json; d=json.load(sys.stdin)['data']; n=len(d); f=lambda k: sum(1 for r in d if r.get(k) is not None); print('rows',n,'| close',f('close_price'),'| 7d',f('change_7d_pct'),'| 52wH',f('high_52w'),'| pos',f('position_52w_pct'),'| pe',f('pe_ttm'),'| pct',f('pe_percentile'))"
date