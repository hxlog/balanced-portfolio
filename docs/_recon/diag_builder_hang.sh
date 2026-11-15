#!/usr/bin/env bash
cd /opt/balanced-portfolio
curl -s --max-time 30 "http://127.0.0.1:3000/builder?mode=basket" -o /tmp/builder.html -w "status:%{http_code} bytes:%{size_download} time:%{time_total}\n"
echo "--- has basket text? ---"
grep -c "一篮子资产" /tmp/builder.html || true
grep -c "加载中" /tmp/builder.html || true
echo "--- web error log tail ---"
tail -60 /root/.pm2/logs/bp-web-error.log | tail -30
