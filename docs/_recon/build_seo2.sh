#!/usr/bin/env bash
set -uo pipefail
cd /opt/balanced-portfolio
git add -A web || true
git -c user.name=deploy -c user.email=deploy@local commit -qm "SEO: metadataBase" || true
cd web
NODE_OPTIONS=--max-old-space-size=1536 nice -n 10 npm run build 2>&1 | tail -2
pm2 restart bp-web >/dev/null
sleep 5
echo "--- canonical ---"
curl -s --max-time 20 http://127.0.0.1:3000/valuation | grep -oE 'rel="canonical" href="[^"]+"' | head -1
curl -s --max-time 20 http://127.0.0.1:3000/valuation/930641 | grep -oE 'rel="canonical" href="[^"]+"' | head -1
echo "--- robots ---"
curl -s --max-time 10 http://127.0.0.1:3000/robots.txt | grep -i sitemap