#!/usr/bin/env bash
set -uo pipefail
cd /opt/balanced-portfolio
echo "=== 部署 ingest 基金业绩扩展 ==="
.git 2>/dev/null || true
git add -A bp_ingest || true
git -c user.name=deploy -c user.email=deploy@local commit -qm "feat(ingest): 每日估值抓取同步基金业绩/经理/规模" || true
pm2 restart bp-ingest >/dev/null
sleep 3
echo "=== 基金费率回填进度 ==="
pgrep -fc backfill_fund_data || echo "fees done"
tail -3 /tmp/fund_backfill.log
su - postgres -c "psql -d postgres -tAc \"select count(*) filter (where management_fee is not null), count(*) filter (where custody_fee is not null), count(*) filter (where established_date is not null), count(*) from bp_fund_master\""
echo "=== 行情健康看护进度 ==="
pgrep -fc quote_coverage_watch || echo "health done"
tail -6 /tmp/quote_health.log 2>/dev/null
