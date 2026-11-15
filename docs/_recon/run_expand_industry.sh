#!/usr/bin/env bash
set -uo pipefail
cd /opt/balanced-portfolio
echo "=== 行业分类扩面 ==="
su - postgres -c "psql -d postgres -v ON_ERROR_STOP=1 -f /tmp/expand_industry.sql" 2>&1 | tail -12
echo "=== 清理估值 API 缓存 ==="
redis-cli -h 127.0.0.1 -p 6379 --scan --pattern "*valuation*" 2>/dev/null | while read -r k; do redis-cli -h 127.0.0.1 -p 6379 DEL "$k" >/dev/null; done
curl -s -o /dev/null -w "indices:%{http_code}\n" --max-time 30 "http://127.0.0.1:8000/api/valuation/indices?limit=1000"
curl -s --max-time 30 "http://127.0.0.1:8000/api/valuation/indices?limit=1000" | .venv/bin/python -c "
import json,sys
d=json.load(sys.stdin)
rows=d.get('data') or []
inds={}
for r in rows:
    ind=r.get('industry')
    if ind: inds[ind]=inds.get(ind,0)+1
print('总行数', len(rows), '| 有行业', sum(inds.values()), '| 行业数', len(inds))
print('top:', sorted(inds.items(), key=lambda x:-x[1])[:8])
"
