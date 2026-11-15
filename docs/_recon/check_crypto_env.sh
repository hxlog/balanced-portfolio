#!/usr/bin/env bash
echo "=== crypto cron ==="
cat /etc/cron.d/bp-crypto-futures 2>/dev/null || echo none
echo "=== relay 状态 ==="
systemctl is-active bp-relay
curl -s -o /dev/null -w "direct binance:%{http_code}\n" --max-time 10 "https://fapi.binance.com/fapi/v1/ping" || echo "direct blocked"
curl -s -o /dev/null -w "relay binance:%{http_code}\n" --proxy http://127.0.0.1:10809 --max-time 20 "https://fapi.binance.com/fapi/v1/ping" || echo "relay fail"
