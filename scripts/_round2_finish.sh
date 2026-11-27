#!/bin/bash
cd /opt/balanced-portfolio || exit 1
exec >> /tmp/round2_finish.log 2>&1
echo "=== START $(date) ==="
set -a; . ./.env; set +a
git pull --ff-only
echo "GIT: $(git log --oneline -1)"
echo '=== index backfill (free sources only) ==='
timeout 3000 .venv/bin/python scripts/index_quotes_free.py --start 2026-11-24 --source cn_index_tx cn_index_sina csindex_perf csindex_oss
echo "INDEX_EXIT=$?"
echo '=== repair clean ==='
timeout 1200 .venv/bin/python scripts/repair_quote_clean.py --apply
echo "CLEAN_EXIT=$?"
echo '=== daily audit ==='
timeout 600 .venv/bin/python scripts/daily_data_audit.py --output /tmp/data_audit_round2.json
echo "AUDIT_EXIT=$?"
echo '=== cron files ==='
ls -1 /etc/cron.d/bp-* 2>/dev/null
echo '=== DONE $(date) ==='
