#!/usr/bin/env bash
UA="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0 Safari/537.36"
echo "--- with browser UA ---"
curl -s -o /tmp/cd2.json -w "http:%{http_code} time:%{time_total}\n" --max-time 30 -A "$UA" "https://binance-proxy.xushilu.com/?path=/fapi/v1/premiumIndex&symbol=BTCUSDT" || true
head -c 200 /tmp/cd2.json 2>/dev/null || true
echo
echo "--- main site with browser UA ---"
curl -s -o /dev/null -w "xushilu:%{http_code}\n" --max-time 20 -A "$UA" https://xushilu.com/ || true