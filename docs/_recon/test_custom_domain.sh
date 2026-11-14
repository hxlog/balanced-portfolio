#!/usr/bin/env bash
echo "--- dns ---"
getent hosts binance-proxy.xushilu.com | head -2 || true
echo "--- custom domain from server ---"
curl -s -o /tmp/cd.json -w "http:%{http_code} time:%{time_total}\n" --max-time 30 "https://binance-proxy.xushilu.com/?path=/fapi/v1/premiumIndex&symbol=BTCUSDT" || true
head -c 300 /tmp/cd.json 2>/dev/null || true