#!/usr/bin/env bash
set -uo pipefail
cd /opt/balanced-portfolio
echo "=== 全量风险指标计算 ==="
timeout 600 .venv/bin/python scripts/compute_fund_risk.py 2>&1 | grep -v Warning | tail -2
su - postgres -c "psql -d postgres -tAc \"select count(*) from bp_fund_risk\""
echo "=== 重算后示例（000300 前 3 只） ==="
.venv/bin/python - <<'PY'
import json, urllib.request
d = json.load(urllib.request.urlopen("http://127.0.0.1:8000/api/valuation/000300", timeout=60))
for f in (d.get("data") or {}).get("tracker_funds", [])[:3]:
    print(f.get("fund_code"), f.get("ann_vol_1y"), f.get("max_dd_1y"), f.get("tracking_error_1y"), f.get("info_ratio_1y"))
PY
echo "=== 失效详情缓存 ==="
TOKEN=$(grep -E "^BP_INTERNAL_REVALIDATE_TOKEN=" .env | cut -d= -f2- | tr -d '\r')
curl -s -X POST "http://127.0.0.1:3000/api/revalidate/valuation" -H "X-Internal-Token: $TOKEN" -H "Content-Type: application/json" | head -c 120; echo
