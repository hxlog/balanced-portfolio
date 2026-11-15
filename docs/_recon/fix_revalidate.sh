#!/usr/bin/env bash
set -uo pipefail
cd /opt/balanced-portfolio
echo "--- .env token 是否存在 ---"
grep -c "^BP_INTERNAL_REVALIDATE_TOKEN=" .env || true
echo "--- pm2 bp-web env ---"
pm2 env 1 2>/dev/null | grep -c "BP_INTERNAL_REVALIDATE_TOKEN" || true
echo "--- 重启 web 并注入 env ---"
pm2 restart bp-web --update-env >/dev/null
sleep 6
.venv/bin/python /tmp/trigger_revalidate.py || true
