#!/usr/bin/env bash
for i in 1 2 3; do curl -s -o /dev/null -w "assets-api:%{http_code} %{time_total}s\n" --max-time 30 "http://127.0.0.1:8000/api/assets?limit=5"; done
curl -s -o /dev/null -w "builder:%{http_code} %{time_total}s\n" --max-time 30 "http://127.0.0.1:3000/builder?mode=basket"
curl -s -o /dev/null -w "dashboard:%{http_code} %{time_total}s\n" --max-time 30 "http://127.0.0.1:3000/dashboard"
