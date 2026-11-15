#!/usr/bin/env bash
curl -s -o /dev/null -w "api:%{http_code} " --max-time 8 http://127.0.0.1:8000/api/health
curl -s -o /dev/null -w "web:%{http_code}\n" --max-time 8 http://127.0.0.1:3000/valuation
uptime
free -h | head -2