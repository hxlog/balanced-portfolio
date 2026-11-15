#!/usr/bin/env bash
set -uo pipefail
cd /opt/balanced-portfolio
git add -A web bp_api bp_ingest ddl scripts docs || true
git -c user.name=deploy -c user.email=deploy@local commit -qm "feat(crypto): 合约监控并入 /crypto；大户多空/资金费率30日分位/Smart Money 乖离/OI 24h 变化卡片与合约表；数据回填与每日 cron" || true
cd web
NODE_OPTIONS=--max-old-space-size=1536 nice -n 10 npm run build 2>&1 | tail -4
pm2 restart bp-web >/dev/null
sleep 6
curl -s -o /dev/null -w "crypto:%{http_code} %{time_total}s\n" --max-time 40 "http://127.0.0.1:3000/crypto"
curl -s -o /dev/null -w "old:%{http_code}\n" --max-time 40 "http://127.0.0.1:3000/crypto-futures"
