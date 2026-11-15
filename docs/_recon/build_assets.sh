#!/usr/bin/env bash
set -uo pipefail
cd /opt/balanced-portfolio
pm2 restart bp-api >/dev/null
sleep 4
echo "=== API 验证 ==="
.venv/bin/python - <<'PY'
import json, urllib.request
d = json.load(urllib.request.urlopen("http://127.0.0.1:8000/api/assets/unified?q=600519&limit=5", timeout=60))
print("rows:", len(d.get("data") or []), "total:", (d.get("meta") or {}).get("total"))
for row in (d.get("data") or [])[:3]:
    print(row["type"], row["code"], row["name"], row["last_date"])
d2 = json.load(urllib.request.urlopen("http://127.0.0.1:8000/api/assets/unified?type=index&limit=3", timeout=60))
print("index rows:", len(d2.get("data") or []))
d3 = json.load(urllib.request.urlopen("http://127.0.0.1:8000/api/assets/unified?type=fund&q=005827&limit=3", timeout=60))
print("fund rows:", len(d3.get("data") or []))
PY
echo "=== 前端构建 ==="
git add -A web bp_api ddl scripts docs || true
git -c user.name=deploy -c user.email=deploy@local commit -qm "feat(assets): 统一资产池 API/页面（股票/指数/基金/ETF，三口径复权）、Navbar 入口；A股/基金全量回填脚本" || true
cd web
NODE_OPTIONS=--max-old-space-size=1536 nice -n 10 npm run build 2>&1 | tail -3
pm2 restart bp-web >/dev/null
sleep 6
curl -s -o /dev/null -w "assets:%{http_code} %{time_total}s\n" --max-time 40 "http://127.0.0.1:3000/assets"
