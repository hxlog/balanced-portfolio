# -*- coding: utf-8 -*-
"""本地验证 Bybit+OKX 备用口径（不落库）。"""
import os, sys, json, time
sys.path.insert(0, ".")
sys.stdout.reconfigure(encoding="utf-8")
os.environ["BP_BINANCE_PROXY_URL"] = "https://binance-proxy.xushilu.com"
from bp_ingest import crypto_futures_fallback as fb

t0 = time.time()
contracts = fb.fetch_contracts(None, limit=5)
print("contracts:", [(c["contract_code"], c["oi_notional_rank"]) for c in contracts], "took", round(time.time()-t0,1))
if contracts:
    rows = fb.fetch_snapshot_5m(contracts)
    for r in rows[:3]:
        print({k: (round(v,4) if isinstance(v,float) else v) for k,v in r.items()})
    print("snapshots:", len(rows), "took", round(time.time()-t0,1))
