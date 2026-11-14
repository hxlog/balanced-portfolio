#!/usr/bin/env bash
set -uo pipefail
cd /opt/balanced-portfolio
git add -A bp_api/rate_limit.py bp_api/auth.py bp_api/main.py bp_api/public_api.py || true
git -c user.name=deploy -c user.email=deploy@local commit -qm "P2: 令牌限流/请求审计" || true
git log --oneline -1
pm2 restart bp-api >/dev/null
sleep 5
echo "--- rate limit test ---"
.venv/bin/python /tmp/verify_ratelimit.py 2>&1 | tail -5
echo "--- request log rows ---"
su - postgres -c "psql -d postgres -tAc \"select count(*) from bp_api_request_log\""
echo "--- health ---"
curl -s -o /dev/null -w "valuation-page:%{http_code}\n" http://127.0.0.1:3000/valuation/930641