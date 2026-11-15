#!/usr/bin/env bash
set -uo pipefail
cd /opt/balanced-portfolio
pm2 restart bp-api >/dev/null
sleep 4
.venv/bin/python - <<'PY'
import json, urllib.request
payload = json.dumps({
    "assets": [
        {"symbol": "510300", "source": "etf_em"},
        {"symbol": "000905", "source": "cn_index_em"},
    ],
    "method": "equal_weight",
    "lookback_days": 156,
    "start": "2024-01-01",
    "end": "2026-11-14",
    "rebalance_band": 0.05,
}).encode()
req = urllib.request.Request("http://127.0.0.1:8000/api/basket/backtest", data=payload, headers={"Content-Type": "application/json"})
try:
    body = json.load(urllib.request.urlopen(req, timeout=120))
    print("equal_weight_nav:", len(body.get("equal_weight_nav") or []))
    print("equal_weight_metrics:", body.get("equal_weight_metrics"))
    print("rebalance_events:", len(body.get("rebalance_events") or []))
    ev = (body.get("rebalance_events") or [None])[0]
    print("first event:", {k: ev.get(k) for k in ("trade_date", "reason", "turnover")} if ev else None)
    print("assets sample:", (ev or {}).get("assets", [])[:2])
except Exception as exc:
    print("FAIL", type(exc).__name__, str(exc)[:300])
PY
