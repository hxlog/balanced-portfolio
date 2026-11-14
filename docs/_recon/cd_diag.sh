#!/usr/bin/env bash
echo "--- root path ---"
curl -s -D /tmp/h1.txt -o /tmp/b1.txt -w "http:%{http_code}\n" --max-time 25 "https://binance-proxy.xushilu.com/" || true
grep -iE "^(cf-ray|cf-mitigated|server|x-frame|content-type)" /tmp/h1.txt || true
echo "--- body ---"
head -c 900 /tmp/b1.txt || true