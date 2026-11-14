#!/usr/bin/env bash
echo "--- worker from server ---"
curl -s -o /tmp/proxy_test.json -w "http:%{http_code} time:%{time_total}\n" --max-time 30 "https://binance-proxy.prologue.workers.dev/?path=/fapi/v1/premiumIndex&symbol=BTCUSDT" || true
head -c 300 /tmp/proxy_test.json 2>/dev/null || true
echo
echo "--- binance direct from server ---"
curl -s -o /dev/null -w "direct:%{http_code} time:%{time_total}\n" --max-time 10 "https://fapi.binance.com/fapi/v1/premiumIndex?symbol=BTCUSDT" || true