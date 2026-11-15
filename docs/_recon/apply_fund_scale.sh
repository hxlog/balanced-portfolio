#!/usr/bin/env bash
set -uo pipefail
cd /opt/balanced-portfolio
echo "=== 迁移 65（生产 + 测试库） ==="
su - postgres -c "psql -d postgres -v ON_ERROR_STOP=1 -f /opt/balanced-portfolio/ddl/65_index_fund_scale.sql" 2>&1 | tail -3
su - postgres -c "psql -d bp_mig_test -v ON_ERROR_STOP=1 -f /opt/balanced-portfolio/ddl/65_index_fund_scale.sql" 2>&1 | tail -2
su - postgres -c "psql -d postgres -tAc \"select count(*), count(aum_sum), max(aum_sum) from bp_index_fund_scale\""
echo "=== 重启 API 并验证字段 ==="
pm2 restart bp-api >/dev/null
sleep 5
redis-cli -h 127.0.0.1 -p 6379 --scan --pattern "*valuation*" 2>/dev/null | while read -r k; do redis-cli -h 127.0.0.1 -p 6379 DEL "$k" >/dev/null; done
curl -s --max-time 40 "http://127.0.0.1:8000/api/valuation/indices?limit=5" | .venv/bin/python -c "
import json,sys
d=json.load(sys.stdin)
for r in (d.get('data') or [])[:5]:
    print(r.get('index_code'), r.get('name'), 'roe=', r.get('roe_ttm'), 'fund_aum=', r.get('fund_aum'), 'fund_count=', r.get('fund_count'))
"
