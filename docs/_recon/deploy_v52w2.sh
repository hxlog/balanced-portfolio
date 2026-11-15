#!/usr/bin/env bash
set -uo pipefail
cd /opt/balanced-portfolio
git add -A web/app/valuation/ValuationHome.tsx web/lib/valuation-types.ts web/lib/valuation-api-map.ts
git -c user.name=deploy -c user.email=deploy@local commit -qm "估值表：52 周位置列 + 7 日涨跌/52 周字段" || true
grep -c "52 周位置" web/app/valuation/ValuationHome.tsx
cd web
NODE_OPTIONS=--max-old-space-size=1536 nice -n 10 npm run build 2>&1 | tail -5