#!/usr/bin/env bash
cd /opt/balanced-portfolio
grep -c '52 周位置' web/app/valuation/ValuationHome.tsx || echo 0
grep -c 'position_52w_pct' web/lib/valuation-api-map.ts || echo 0
git log --oneline -2
git status --porcelain=v1 | head -5
grep -o '52 周位置' web/.next/server/app/valuation*.js 2>/dev/null | head -2 || echo 'not in built chunks'