#!/usr/bin/env bash
cd /opt/balanced-portfolio
echo "=== 净值回填 ==="
pgrep -fc backfill_fund_nav || echo done
tail -3 /tmp/fund_nav_backfill2.log | tr -d "\r"
su - postgres -c "psql -d postgres -tAc \"select count(distinct fund_code), count(*) from bp_fund_nav_daily\""
echo "=== 计算基金风险指标 ==="
.venv/bin/python scripts/compute_fund_risk.py 2>&1 | tail -3
echo "=== API 验证 ==="
.venv/bin/python - <<'PY'
import json, urllib.request
d = json.load(urllib.request.urlopen("http://127.0.0.1:8000/api/valuation/000300", timeout=60))
funds = (d.get("data") or {}).get("tracker_funds") or []
print("funds:", len(funds))
for f in funds[:3]:
    print({k: f.get(k) for k in ("fund_code","name","ann_vol_1y","max_dd_1y","tracking_error_1y","info_ratio_1y")})
s = json.load(urllib.request.urlopen("http://127.0.0.1:8000/api/valuation/000300/benchmark-stats?benchmark=000300", timeout=60))
print("stats:", json.dumps(s.get("data"), ensure_ascii=False)[:400])
c = json.load(urllib.request.urlopen("http://127.0.0.1:8000/api/valuation/funds/compare?codes=SH510300,SH510310&benchmark=000300", timeout=60))
print("compare:", json.dumps(c.get("items"), ensure_ascii=False)[:400])
PY
