#!/usr/bin/env bash
cd /opt/balanced-portfolio
echo '--- api timing ---'
curl -s -o /dev/null -w 'indices:%{http_code} time:%{time_total}\n' 'http://127.0.0.1:8000/api/valuation/indices?limit=600'
echo '--- page mock marker ---'
curl -s http://127.0.0.1:3000/valuation | grep -oE 'Mock 示例|尚未接入 API|上证指数' | sort | uniq -c
echo '--- page timing ---'
curl -s -o /dev/null -w 'page:%{http_code} time:%{time_total}\n' http://127.0.0.1:3000/valuation