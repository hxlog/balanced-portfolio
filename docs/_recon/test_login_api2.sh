#!/usr/bin/env bash
cd /opt/balanced-portfolio
echo '--- login api test ---'
curl -s -X POST -H 'Content-Type: application/json' -d '{"email":"qa-bot@example.com","password":"QaBot!2026Test"}' http://127.0.0.1:8000/api/auth/login | head -c 400
echo