#!/usr/bin/env bash
cd /opt/balanced-portfolio
curl -s --max-time 30 "http://127.0.0.1:3000/builder?mode=basket" -o /tmp/b.html -w "bytes:%{size_download}\n"
echo "--- basket text count ---"
grep -c "一篮子资产" /tmp/b.html || true
echo "--- script chunks (first 8) ---"
grep -o '/_next/static/chunks/[^"]*\.js' /tmp/b.html | sort -u | head -8 > /tmp/chunks.txt
cat /tmp/chunks.txt
echo "--- fetch each ---"
while read -r c; do code=$(curl -s -o /dev/null -w "%{http_code}" --max-time 10 "http://127.0.0.1:3000$c"); echo "$code $c"; done < /tmp/chunks.txt
echo "--- web err log (new) ---"
tail -30 /root/.pm2/logs/bp-web-error.log | tail -14
