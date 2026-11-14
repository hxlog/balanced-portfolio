#!/usr/bin/env bash
echo "--- premiumIndex from server (custom domain) ---"
curl -s -D /tmp/h2.txt -o /tmp/b2.txt -w "http:%{http_code} time:%{time_total}\n" --max-time 25 "https://binance-proxy.xushilu.com/?path=/fapi/v1/premiumIndex&symbol=BTCUSDT" || true
grep -iE "^(cf-ray|server|content-type)" /tmp/h2.txt || true
head -c 400 /tmp/b2.txt || true
echo
echo "--- exchangeInfo ---"
curl -s -o /tmp/b3.txt -w "http:%{http_code}\n" --max-time 30 "https://binance-proxy.xushilu.com/?path=/fapi/v1/exchangeInfo" || true
head -c 200 /tmp/b3.txt || true