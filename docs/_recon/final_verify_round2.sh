#!/usr/bin/env bash
set -uo pipefail
cd /opt/balanced-portfolio
echo "=== 页面 ==="
for p in /valuation /valuation/000300 /valuation/930641; do
  curl -s -o /dev/null -w "  $p -> %{http_code} %{time_total}s\n" --max-time 40 "http://127.0.0.1:3000$p"
done
echo "=== 基金费率进度 ==="
pgrep -fc "backfill_fund_data.*--fees" || echo "fees done"
grep -a "fees progress\|fees done" /tmp/fund_fees2.log | tail -2
su - postgres -c "psql -d postgres -tAc \"select count(*) filter (where management_fee is not null), count(*) filter (where established_date is not null), count(*) filter (where fund_scale is not null), count(*) from bp_fund_master\""
echo "=== 行情健康 ==="
su - postgres -c "psql -d postgres -tAc \"select status, count(*) from bp_index_quote_health group by 1 order by 2 desc\""
echo "=== API 详情基金字段 ==="
.venv/bin/python - <<'PY'
import json, urllib.request
d = json.load(urllib.request.urlopen("http://127.0.0.1:8000/api/valuation/000300", timeout=40))
data = d.get("data") or {}
funds = data.get("tracker_funds") or []
print("funds:", len(funds), "weight_method:", data.get("weight_method"))
if funds:
    f = funds[0]
    print({k: f.get(k) for k in ("fund_code","name","aum","fund_scale","management_fee","custody_fee","established_date","ret_12m","ytd","manager")})
PY
