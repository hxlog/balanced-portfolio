#!/usr/bin/env bash
set -uo pipefail
cd /opt/balanced-portfolio
git apply --check /tmp/v52w.patch && git apply --index /tmp/v52w.patch
git -c user.name=deploy -c user.email=deploy@local commit -qm "估值表 52 周位置列"
cd web
NODE_OPTIONS=--max-old-space-size=1536 nice -n 10 npm run build 2>&1 | tail -5