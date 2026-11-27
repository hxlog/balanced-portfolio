#!/bin/bash
cd /opt/balanced-portfolio || exit 1
exec >> /tmp/deploy_round2.log 2>&1
echo "=== START $(date) ==="
set -a
. ./.env
set +a
git pull --ff-only
echo "GIT: $(git log --oneline -1)"
echo '=== migrations 81/82 ==='
for f in ddl/81_valuation_latest_roe.sql ddl/82_market_data_audit.sql; do echo "-- $f"; psql -X -v ON_ERROR_STOP=1 -f "$f" || echo "MIGRATION_FAILED $f"; done
echo '=== stop pm2 for build ==='
pm2 stop bp-api bp-web bp-worker bp-beat bp-etl || true
free -m
cd web
rm -rf .next
echo '=== npm ci (next 16.4.6) ==='
npm ci --legacy-peer-deps
echo "NPMCI_EXIT=$?"
export BP_API_BASE="http://127.0.0.1:8000"
export BP_SITE_URL="https://xushilu.com"
npm run build
BUILD_EXIT=$?
echo "BUILD_EXIT=$BUILD_EXIT"
cd ..
echo '=== restart pm2 ==='
pm2 restart deploy/ecosystem.config.cjs --update-env || pm2 start deploy/ecosystem.config.cjs
pm2 stop bp-ingest || true
pm2 save
sleep 8
curl -s -m 5 http://127.0.0.1:8000/api/health; echo
curl -s -m 5 -o /dev/null -w 'web=%{http_code}\n' http://127.0.0.1:3000/
echo '=== data backfill: index quotes ==='
timeout 2400 .venv/bin/python scripts/index_quotes_free.py --start 2026-11-24
echo "INDEX_EXIT=$?"
echo '=== legacy backfill ==='
timeout 1800 .venv/bin/python scripts/backfill_legacy_quotes.py --apply
echo "LEGACY_EXIT=$?"
echo '=== repair clean/backlog ==='
timeout 1200 .venv/bin/python scripts/repair_quote_clean.py --apply
echo "CLEAN_EXIT=$?"
echo '=== valuation + MVI ==='
timeout 1800 .venv/bin/python -m bp_ingest.valuation_run
echo "VAL_EXIT=$?"
timeout 900 .venv/bin/python scripts/compute_mvi.py
echo "MVI_EXIT=$?"
echo '=== market valuation + 10Y ==='
timeout 300 .venv/bin/python -m bp_ingest.market_valuation
echo "MV_EXIT=$?"
timeout 600 .venv/bin/python -m bp_ingest.risk_free --start 2017
echo "RF_EXIT=$?"
echo '=== cffex ==='
timeout 600 .venv/bin/python -m bp_ingest cffex-incremental
echo "CFFEX_EXIT=$?"
echo '=== demo basket recompute ==='
timeout 900 .venv/bin/python scripts/seed_demo_basket.py
echo "SEED_EXIT=$?"
echo '=== daily audit ==='
timeout 600 .venv/bin/python scripts/daily_data_audit.py --output /tmp/data_audit_round2.json
echo "AUDIT_EXIT=$?"
echo '=== install cron ==='
cat > /etc/cron.d/bp-index-quotes-free <<'EOF'
0,15,30,45 16-23 * * 1-5 root cd /opt/balanced-portfolio && set -a && . ./.env && set +a && flock -n /tmp/bp-index-quotes.lock nice -n 12 ionice -c2 -n7 .venv/bin/python scripts/index_quotes_free.py >> /var/log/bp-index-quotes-free.log 2>&1
0 9 * * 1-5 root cd /opt/balanced-portfolio && set -a && . ./.env && set +a && flock -n /tmp/bp-index-quotes.lock nice -n 12 ionice -c2 -n7 .venv/bin/python scripts/index_quotes_free.py >> /var/log/bp-index-quotes-free.log 2>&1
EOF
cat > /etc/cron.d/bp-data-audit <<'EOF'
30 9 * * 1-5 root cd /opt/balanced-portfolio && set -a && . ./.env && set +a && nice -n 12 .venv/bin/python scripts/daily_data_audit.py >> /var/log/bp-data-audit.log 2>&1
EOF
cat > /etc/cron.d/bp-market-valuation <<'EOF'
20 21 * * 1-5 root cd /opt/balanced-portfolio && set -a && . ./.env && set +a && nice -n 12 .venv/bin/python -m bp_ingest.market_valuation >> /var/log/bp-market-valuation.log 2>&1
EOF
cat > /etc/cron.d/bp-risk-free <<'EOF'
40 21 * * 1-5 root cd /opt/balanced-portfolio && set -a && . ./.env && set +a && nice -n 12 .venv/bin/python -m bp_ingest.risk_free --days 30 >> /var/log/bp-risk-free.log 2>&1
EOF
cat > /etc/cron.d/bp-legacy-backfill <<'EOF'
5 21 * * 1-5 root cd /opt/balanced-portfolio && set -a && . ./.env && set +a && flock -n /tmp/bp-legacy-backfill.lock nice -n 12 ionice -c2 -n7 .venv/bin/python scripts/backfill_legacy_quotes.py --apply >> /var/log/bp-legacy-backfill.log 2>&1
EOF
chmod 644 /etc/cron.d/bp-index-quotes-free /etc/cron.d/bp-data-audit /etc/cron.d/bp-market-valuation /etc/cron.d/bp-risk-free /etc/cron.d/bp-legacy-backfill
echo '=== DONE $(date) build_exit='$BUILD_EXIT' ==='
