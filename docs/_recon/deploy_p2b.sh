#!/usr/bin/env bash
set -euo pipefail
cd /opt/balanced-portfolio
git apply --check /tmp/p2b.patch
git apply --index /tmp/p2b.patch
git -c user.name=deploy -c user.email=deploy@local commit -qm "P2: 限流/审计/SDK"
pm2 restart bp-api >/dev/null
sleep 4
echo "--- rate limit test ---"
.venv/bin/python /tmp/verify_ratelimit.py 2>&1 | tail -5
echo "--- request log ---"
su - postgres -c "psql -d postgres -tAc \"select count(*) from bp_api_request_log\""