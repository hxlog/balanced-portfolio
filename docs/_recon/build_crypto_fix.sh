#!/usr/bin/env bash
set -uo pipefail
cd /opt/balanced-portfolio
git add -A web || true
git -c user.name=deploy -c user.email=deploy@local commit -qm "fix(crypto): 映射新增大户/资金费率/SmartMoney 字段" || true
cd web
NODE_OPTIONS=--max-old-space-size=1536 nice -n 10 npm run build 2>&1 | tail -3
pm2 restart bp-web >/dev/null
sleep 6
curl -s -o /dev/null -w "crypto:%{http_code}\n" --max-time 40 "http://127.0.0.1:3000/crypto"
