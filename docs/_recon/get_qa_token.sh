#!/usr/bin/env bash
cd /opt/balanced-portfolio
TOKEN=$(curl -s -X POST -H 'Content-Type: application/json' -d '{"email":"qa-bot@example.com","password":"QaBot!2026Test"}' http://127.0.0.1:8000/api/auth/login | python3 -c 'import sys,json; d=json.load(sys.stdin); print(d.get("token") or d.get("access_token") or "")')
echo "token_len=${#TOKEN}"
echo "$TOKEN" > /tmp/qa_token.txt
curl -s -H "Authorization: Bearer $TOKEN" http://127.0.0.1:8000/api/auth/me | head -c 300