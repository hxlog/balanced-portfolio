# -*- coding: utf-8 -*-
"""用 SDK 对线上 API 做端到端验收（本机直连 HTTPS）。"""
import os, sys
for k in ("HTTP_PROXY", "HTTPS_PROXY", "ALL_PROXY", "http_proxy", "https_proxy"):
    os.environ.pop(k, None)
sys.path.insert(0, "sdk")
sys.stdout.reconfigure(encoding="utf-8")
from bpdata import Client

TOKEN = os.environ["BP_E2E_TOKEN"]
client = Client(TOKEN, base_url="https://xushilu.com", timeout=60)

percentiles = client.percentile(["930641"], metrics=["pe_ttm"], windows=["5y"])
print("percentile rows:", len(percentiles), "first:", percentiles[0] if percentiles else None)
detail = client.detail("930641")
print("detail name:", detail.get("name"), "| pe:", detail.get("pe_ttm"), "| constituents:", len(detail.get("constituents") or []), "| funds:", len(detail.get("tracker_funds") or []))
valuation = client.valuation(["000300"], start="2026-11-01")
print("valuation rows:", len(valuation), "first:", valuation[0] if valuation else None)
bond = client.bond_yield(start="2026-11-01")
print("bond rows:", len(bond), "last:", bond[-1] if bond else None)
