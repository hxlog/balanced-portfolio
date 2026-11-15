#!/usr/bin/env bash
set -uo pipefail
cd /opt/balanced-portfolio
git apply --check /tmp/ui_refresh.patch && git apply --index /tmp/ui_refresh.patch
git -c user.name=deploy -c user.email=deploy@local commit -qm "前端改版：估值页 + builder 篮子模式"
echo "--- routes sanity ---"
.venv/bin/python -c "import bp_api.main; print('api ok')"
cd web
NODE_OPTIONS=--max-old-space-size=1536 nice -n 10 npm run build 2>&1 | tail -6