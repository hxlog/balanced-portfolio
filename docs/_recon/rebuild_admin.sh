#!/usr/bin/env bash
set -uo pipefail
cd /opt/balanced-portfolio
echo "component exists: $(test -f web/components/UnifiedAssetsPanel.tsx && echo yes || echo no)"
grep -c "UnifiedAssetsPanel" web/app/admin/assets/page.tsx || true
cd web
NODE_OPTIONS=--max-old-space-size=1536 nice -n 10 npm run build 2>&1 | tail -3
pm2 restart bp-web >/dev/null
sleep 6
curl -s --max-time 30 "http://127.0.0.1:3000/admin/assets" -o /tmp/admin.html
python3 -c "h=open('/tmp/admin.html',encoding='utf-8').read(); print('has-统一资产池:', '统一资产池' in h)"
