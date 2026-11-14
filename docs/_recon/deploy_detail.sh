#!/usr/bin/env bash
set -euo pipefail
cd /opt/balanced-portfolio
git apply --check /tmp/p1_detail.patch
git apply --index /tmp/p1_detail.patch
git -c user.name=deploy -c user.email=deploy@local commit -qm "P1: 指数详情页（D1 + 三 Tab）"
git log --oneline -1
echo "--- build ---"
cd web
NODE_OPTIONS=--max-old-space-size=1536 nice -n 10 npm run build 2>&1 | tail -8