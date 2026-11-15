#!/usr/bin/env bash
set -uo pipefail
cd /opt/balanced-portfolio
grep -q "^BP_SITE_URL=" .env && sed -i "s|^BP_SITE_URL=.*|BP_SITE_URL=https://xushilu.com|" .env || echo "BP_SITE_URL=https://xushilu.com" >> .env
grep "^BP_SITE_URL=" .env
echo "--- 重启 web 让环境变量生效 ---"
pm2 restart bp-web --update-env >/dev/null
sleep 5
echo done