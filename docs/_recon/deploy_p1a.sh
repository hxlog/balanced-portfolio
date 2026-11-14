#!/usr/bin/env bash
set -uo pipefail
cd /opt/balanced-portfolio
git add -A bp_ingest/valuation_ingest.py bp_api/repositories_valuation.py ddl/55_constituents_funds_quality.sql
git -c user.name=deploy -c user.email=deploy@local commit -qm "P1: 成分股/跟踪基金落库" || true
git log --oneline -1
pm2 restart bp-api >/dev/null
setsid nohup .venv/bin/python -c "from bp_ingest.valuation_run import main; import sys; sys.exit(main())" > /tmp/valuation_ingest3.log 2>&1 < /dev/null &
echo "backfill launched"