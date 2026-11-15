#!/usr/bin/env bash
set -uo pipefail
cd /opt/balanced-portfolio
git add -A bp_api bp_ingest ddl scripts
git -c user.name=deploy -c user.email=deploy@local commit -qm "feat: 指数列表支持窗口/指标/行业筛选 + 全历史高低 + 52周涨跌；overview 增加代表性宽基代理分位" || true
pm2 restart bp-api >/dev/null
sleep 5
echo "=== health ==="
curl -s -o /dev/null -w "api:%{http_code}\n" --max-time 10 http://127.0.0.1:8000/api/health
echo "=== overview proxies ==="
curl -s --max-time 40 "http://127.0.0.1:8000/api/valuation/overview?window=5y" > /tmp/ov.json
.venv/bin/python - <<PY
import json
d = json.load(open("/tmp/ov.json"))
meta = d.get("meta") or {}
print("boards:", len(d.get("data") or []), "window:", meta.get("window"))
for p in (meta.get("proxies") or []):
    print(" proxy", p.get("index_code"), p.get("name"), "pe=", p.get("pe_ttm"), "pe_pct=", p.get("pe_percentile"), "pb_pct=", p.get("pb_percentile"), p.get("trade_date"))
PY
echo "=== indices window/metric/industry ==="
curl -s --max-time 60 "http://127.0.0.1:8000/api/valuation/indices?limit=5&window=1y&metric=pb" > /tmp/idx1.json
curl -s --max-time 60 "http://127.0.0.1:8000/api/valuation/indices?limit=5&industry=%E9%93%B6%E8%A1%8C" > /tmp/idx2.json
.venv/bin/python - <<PY
import json
for path, label in (("/tmp/idx1.json", "window=1y metric=pb"), ("/tmp/idx2.json", "industry=银行")):
    d = json.load(open(path))
    rows = d.get("data") or []
    meta = d.get("meta") or {}
    print(label, "rows:", len(rows), "window:", meta.get("window"), "metric:", meta.get("metric"), "industry:", meta.get("industry"))
    if rows:
        r = rows[0]
        print("  sample:", r.get("index_code"), r.get("name"), "pe_pct:", r.get("pe_percentile"),
              "pb_pct:", r.get("pb_percentile"), "metric_pct:", r.get("metric_percentile"),
              "high_all:", r.get("high_all"), "dist_all:", r.get("dist_from_all_high_pct"),
              "chg52w:", r.get("change_52w_pct"), "industry:", r.get("industry"))
PY
