#!/usr/bin/env bash
set -euo pipefail
cd /tmp
rm -rf /tmp/xray-linux && mkdir -p /tmp/xray-linux
unzip -o -q /tmp/xray-linux.zip -d /tmp/xray-linux
install -m 0755 /tmp/xray-linux/xray /usr/local/bin/bp-relay
mkdir -p /etc/bp-relay
cp /tmp/xray_config.json /etc/bp-relay/config.json
chmod 600 /etc/bp-relay/config.json
/usr/local/bin/bp-relay -test -c /etc/bp-relay/config.json 2>&1 | tail -3
cat > /etc/systemd/system/bp-relay.service <<'EOF'
[Unit]
Description=Balanced Portfolio outbound market relay
After=network-online.target
Wants=network-online.target

[Service]
Type=simple
ExecStart=/usr/local/bin/bp-relay run -c /etc/bp-relay/config.json
Restart=on-failure
RestartSec=5
NoNewPrivileges=true

[Install]
WantedBy=multi-user.target
EOF
systemctl daemon-reload
systemctl enable --now bp-relay
sleep 3
systemctl is-active bp-relay
ss -tlnp | grep -E "10808|10809" || true