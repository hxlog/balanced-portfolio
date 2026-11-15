#!/usr/bin/env bash
cd /opt/balanced-portfolio
echo "=== server dashboard page ==="
grep -n "DashboardBaskets\|篮子组合" web/app/dashboard/page.tsx || echo "not found in page"
ls -la web/app/dashboard/ | head
echo "=== server component ==="
ls web/app/dashboard/DashboardBaskets.tsx 2>/dev/null || echo "component missing"
echo "=== HTML check ==="
curl -s --max-time 40 "http://127.0.0.1:3000/dashboard" -o /tmp/dash.html -w "status:%{http_code} bytes:%{size_download}\n"
grep -c "篮子组合" /tmp/dash.html || true
grep -o "DashboardBaskets" /tmp/dash.html | head -1
echo "=== git log dashboard ==="
git log --oneline -3 -- web/app/dashboard/
