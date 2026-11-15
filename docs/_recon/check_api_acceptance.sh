#!/usr/bin/env bash
cd /opt/balanced-portfolio
echo "=== 管理端鉴权（应 401/403） ==="
for p in "/api/admin/api-tokens" "/api/admin/users" "/api/admin/assets"; do
  curl -s -o /dev/null -w "$p -> %{http_code}\n" --max-time 10 "http://127.0.0.1:8000$p"
done
echo "=== 对外 API 无 token（应 401） ==="
curl -s -o /dev/null -w "v1-indices -> %{http_code}\n" --max-time 10 "http://127.0.0.1:8000/api/v1/index/valuation?codes=000300"
echo "=== 限流头验证 ==="
TOKEN=$(.venv/bin/python scripts/issue_e2e_token.py 2>/dev/null | grep TOKEN= | cut -d= -f2)
for i in $(seq 1 61); do code=$(curl -s -o /dev/null -w "%{http_code}" -H "Authorization: Bearer $TOKEN" "http://127.0.0.1:8000/api/v1/index/percentile?codes=930641&metrics=pe_ttm&windows=5y"); done; echo "last=$code"
curl -s -D - -o /dev/null -H "Authorization: Bearer $TOKEN" "http://127.0.0.1:8000/api/v1/index/percentile?codes=930641" | grep -i "retry-after\|HTTP/" | head -3
echo "=== CSV ==="
curl -s -H "Authorization: Bearer $TOKEN" "http://127.0.0.1:8000/api/v1/index/valuation?codes=930641&format=csv" | head -3