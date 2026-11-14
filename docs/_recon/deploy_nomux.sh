#!/usr/bin/env bash
set -uo pipefail
echo "=== 1) 还原 relay 配置（去掉 mux，vision 不支持） ==="
install -m 600 /tmp/xray_config_nomux.json /etc/bp-relay/config.json
/usr/local/bin/bp-relay -test -c /etc/bp-relay/config.json 2>&1 | tail -1
systemctl restart bp-relay
sleep 3
systemctl is-active bp-relay
echo "=== 2) 串行 10 次 ping 计时（无 mux） ==="
start=$(date +%s%3N)
for i in $(seq 1 10); do curl -s -o /dev/null --proxy http://127.0.0.1:10809 --max-time 20 "https://fapi.binance.com/fapi/v1/ping?x=$i" || echo "fail$i"; done
end=$(date +%s%3N)
echo "serial 10 took: $((end-start)) ms"
echo "=== 3) 部署 session 复用版采集 ==="
cd /opt/balanced-portfolio
git add -A bp_ingest/crypto_futures.py
git -c user.name=deploy -c user.email=deploy@local commit -qm "P5: 采集改用线程本地 Session 复用连接" || true