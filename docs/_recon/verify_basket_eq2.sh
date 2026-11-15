#!/usr/bin/env bash
cd /opt/balanced-portfolio
pm2 restart bp-api >/dev/null
sleep 4
.venv/bin/python - <<'PY'
import json, urllib.request
payload = json.dumps({
    "assets": [{"symbol": "510300", "source": "etf_em"}, {"symbol": "000905", "source": "cn_index_em"}],
    "method": "risk_parity", "lookback_days": 156, "start": "2024-01-01", "end": "2026-11-14", "rebalance_band": 0.05,
}).encode()
req = urllib.request.Request("http://127.0.0.1:8000/api/basket/backtest", data=payload, headers={"Content-Type": "application/json"})
body = json.load(urllib.request.urlopen(req, timeout=120))
print("nav", len(body.get("nav") or []), "eq_nav", len(body.get("equal_weight_nav") or []))
print("eq_metrics", body.get("equal_weight_metrics"))
PY
