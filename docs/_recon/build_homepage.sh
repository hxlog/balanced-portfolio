#!/usr/bin/env bash
set -uo pipefail
cd /opt/balanced-portfolio
git add -A web bp_api docs || true
git -c user.name=deploy -c user.email=deploy@local commit -qm "feat(web): 首页新功能入口与新增能力区块、全局 1600px、移除 Experiment 标签、加密图表 OI 千分位；OTC 金标验证 8/8" || true
cd web
NODE_OPTIONS=--max-old-space-size=1536 nice -n 10 npm run build 2>&1 | tail -3
pm2 restart bp-web >/dev/null
sleep 6
for p in / /crypto /valuation /builder?mode=basket; do curl -s -o /dev/null -w "$p -> %{http_code}\n" --max-time 40 "http://127.0.0.1:3000$p"; done
