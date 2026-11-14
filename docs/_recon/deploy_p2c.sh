#!/usr/bin/env bash
set -euo pipefail
cd /opt/balanced-portfolio
git add -A bp_api/rate_limit.py bp_api/auth.py bp_api/main.py bp_api/public_api.py sdk bp_api/tests/test_rate_limit.py
git -c user.name=deploy -c user.email=deploy@local commit -qm "P2: 令牌限流/请求审计/Python SDK" || true
git log --oneline -1
pm2 restart bp-api >/dev/null
sleep 4
echo "--- rate limit test ---"
.venv/bin/python /tmp/verify_ratelimit.py 2>&1 | tail -5
echo "--- request log rows ---"
su - postgres -c "psql -d postgres -tAc \"select count(*) from bp_api_request_log\""