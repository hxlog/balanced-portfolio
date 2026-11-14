#!/usr/bin/env bash
echo "--- server proxy env ---"
env | grep -iE "http_proxy|https_proxy|all_proxy" || echo "no proxy env"
echo "--- server binance dns ---"
getent hosts fapi.binance.com | head -2 || echo "dns fail"
echo "--- server curl binance (short) ---"
curl -s -o /dev/null -w "http:%{http_code} time:%{time_total}\n" --max-time 8 "https://fapi.binance.com/fapi/v1/ping" || true