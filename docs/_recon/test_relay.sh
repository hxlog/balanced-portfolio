#!/usr/bin/env bash
echo "--- egress ip ---"
curl -s --proxy http://127.0.0.1:10809 --max-time 30 "https://api.ipify.org?format=json" || echo "ip fail"
echo
echo "--- binance premiumIndex ---"
curl -s --proxy http://127.0.0.1:10809 --max-time 30 "https://fapi.binance.com/fapi/v1/premiumIndex?symbol=BTCUSDT" | head -c 200 || echo "binance fail"
echo
echo "--- exchangeInfo count ---"
curl -s --proxy http://127.0.0.1:10809 --max-time 60 "https://fapi.binance.com/fapi/v1/exchangeInfo" | python3 -c "import sys,json; d=json.load(sys.stdin); print(len(d.get('symbols',[])))" 2>/dev/null || echo "parse fail"