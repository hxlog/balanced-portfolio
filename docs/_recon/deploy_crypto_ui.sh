#!/usr/bin/env bash
set -uo pipefail
cd /opt/balanced-portfolio
git apply --check /tmp/crypto_ui.patch && git apply --index /tmp/crypto_ui.patch
git -c user.name=deploy -c user.email=deploy@local commit -qm "P5: 加密合约看板前端"
cd web
NODE_OPTIONS=--max-old-space-size=1536 nice -n 10 npm run build 2>&1 | tail -6