#!/usr/bin/env bash
echo "--- /cffex status ---"
curl -s -o /tmp/cffex.html -w "page:%{http_code} bytes:%{size_download}\n" --max-time 20 http://127.0.0.1:3000/cffex
head -c 200 /tmp/cffex.html
echo
echo "--- api cffex endpoints ---"
for p in "/api/cffex/history?days=10" "/api/cffex/spot" "/api/cffex/statistics?period=3Y"; do
  curl -s -o /dev/null -w "$p -> %{http_code}\n" --max-time 15 "http://127.0.0.1:8000$p"
done
echo "--- bp-web error log ---"
tail -20 /root/.pm2/logs/bp-web-error.log 2>/dev/null | grep -iE "error|Error" | tail -6