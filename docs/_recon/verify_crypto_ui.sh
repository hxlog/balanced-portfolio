#!/usr/bin/env bash
cd /opt/balanced-portfolio
echo "--- route built ---"
ls .next/server/app/crypto-futures 2>/dev/null | head -4 || echo "missing"
pm2 restart bp-web >/dev/null
sleep 6
echo "--- pages ---"
curl -s -o /dev/null -w "crypto-futures:%{http_code}\n" http://127.0.0.1:3000/crypto-futures
curl -s -o /dev/null -w "valuation:%{http_code}\n" http://127.0.0.1:3000/valuation
echo "--- markers ---"
curl -s http://127.0.0.1:3000/crypto-futures | grep -oE "(加密合约看板|BTCUSDT|总未平仓|多空比|5 分钟更新)" | sort | uniq -c
echo "--- external ---"
curl -s -o /dev/null -w "ext:%{http_code}\n" https://xushilu.com/crypto-futures