#!/usr/bin/env bash
echo "--- IPv4 forced ---"
curl -4 -s -D /tmp/h4.txt -o /tmp/b4.txt -w "http:%{http_code} time:%{time_total}\n" --max-time 30 "https://binance-proxy.xushilu.com/?path=/fapi/v1/premiumIndex&symbol=BTCUSDT" || true
grep -iE "^(cf-ray|x-proxy-host|server)" /tmp/h4.txt || true
head -c 200 /tmp/b4.txt || true
echo
echo "--- IPv6 forced ---"
curl -6 -s -D /tmp/h6.txt -o /tmp/b6.txt -w "http:%{http_code}\n" --max-time 25 "https://binance-proxy.xushilu.com/?path=/fapi/v1/premiumIndex&symbol=BTCUSDT" || true
grep -iE "^(cf-ray|x-proxy-host)" /tmp/h6.txt || true