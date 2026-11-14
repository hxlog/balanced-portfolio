#!/usr/bin/env bash
set -uo pipefail
cd /opt/balanced-portfolio
git add -A bp_api/repositories_valuation.py bp_ingest/valuation_job.py bp_ingest/scheduler.py
git -c user.name=deploy -c user.email=deploy@local commit -qm "估值：放开 GLOBAL 市场、增加调度门控" || true
git log --oneline -1
pm2 restart bp-api bp-ingest bp-beat >/dev/null
sleep 3
setsid nohup .venv/bin/python -c "from bp_ingest.valuation_run import main; import sys; sys.exit(main())" > /tmp/valuation_ingest2.log 2>&1 < /dev/null &
echo "backfill launched"
sleep 5
tail -2 /tmp/valuation_ingest2.log