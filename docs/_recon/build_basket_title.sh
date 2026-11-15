#!/usr/bin/env bash
set -uo pipefail
cd /opt/balanced-portfolio
git add -A web || true
git -c user.name=deploy -c user.email=deploy@local commit -qm "dashboard 篮子卡片标题与按钮收尾" || true
cd web
NODE_OPTIONS=--max-old-space-size=1536 nice -n 10 npm run build 2>&1 | tail -3
pm2 restart bp-web >/dev/null
sleep 6
curl -s --max-time 30 "http://127.0.0.1:3000/dashboard?mode=basket" -o /tmp/dbasket.html
python3 -c "h=open('/tmp/dbasket.html',encoding='utf-8').read(); print('title-ok:', '一篮子资产' in h, 'dup-btn:', h.count('新建篮子'))"
