#!/usr/bin/env bash
echo "--- relay status ---"
systemctl is-active bp-relay
systemctl show bp-relay -p NRestarts --value
echo "--- curl via relay (3 tries) ---"
for i in 1 2 3; do
  code=$(curl -s -o /dev/null -w "%{http_code} %{time_total}" --proxy http://127.0.0.1:10809 --max-time 20 "https://fapi.binance.com/fapi/v1/ping?x=$i" || echo fail)
  echo "  try$i: $code"
  sleep 1
done
echo "--- journal relay errors ---"
journalctl -u bp-relay --no-pager -n 8 2>/dev/null | tail -8