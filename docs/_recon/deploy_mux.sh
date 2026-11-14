#!/usr/bin/env bash
set -uo pipefail
cp /etc/bp-relay/config.json /opt/backup/bp-relay-config.json.bak 2>/dev/null || true
install -m 600 /tmp/xray_config_mux.json /etc/bp-relay/config.json
/usr/local/bin/bp-relay -test -c /etc/bp-relay/config.json 2>&1 | tail -2
systemctl restart bp-relay
sleep 3
systemctl is-active bp-relay
echo "--- 10 sequential pings ---"
start=$(date +%s.%N)
for i in $(seq 1 10); do curl -s -o /dev/null --proxy http://127.0.0.1:10809 --max-time 20 "https://fapi.binance.com/fapi/v1/ping?x=$i" || echo "fail$i"; done
end=$(date +%s.%N)
echo "10 pings took: $(echo "$end - $start" | bc)s"
echo "--- 10 parallel pings ---"
start=$(date +%s.%N)
for i in $(seq 1 10); do curl -s -o /dev/null --proxy http://127.0.0.1:10809 --max-time 20 "https://fapi.binance.com/fapi/v1/ping?p=$i" & done; wait
end=$(date +%s.%N)
echo "parallel took: $(echo "$end - $start" | bc)s"