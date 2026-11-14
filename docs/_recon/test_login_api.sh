#!/usr/bin/env bash
cd /opt/balanced-portfolio
echo '--- login api test ---'
curl -s -X POST -H 'Content-Type: application/json' -d '{"email":"qa-bot@example.com","password":"QaBot!2026Test"}' http://127.0.0.1:8000/api/login | head -c 400
echo
echo '--- 路由探测 ---'
grep -rn 'api/login\|api/auth' bp_api/main.py | head -5