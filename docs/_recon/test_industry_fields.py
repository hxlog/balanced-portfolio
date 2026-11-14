# -*- coding: utf-8 -*-
import sys
sys.path.insert(0, "/opt/balanced-portfolio")
sys.stdout.reconfigure(encoding="utf-8")
from bp_ingest.http_session import install_hardened_session
install_hardened_session()
import requests, json
for fields in ["f12,f14,f100", "f12,f14,f127"]:
    try:
        r = requests.get("https://push2.eastmoney.com/api/qt/clist/get", params={
            "pn": "1", "pz": "3", "po": "1", "np": "1", "fltt": "2", "invt": "2", "fid": "f3",
            "fs": "m:1+t:2", "fields": fields}, timeout=20)
        j = r.json()
        diff = (j.get("data") or {}).get("diff") or []
        print(fields, "->", json.dumps(diff[:2], ensure_ascii=False)[:200])
    except Exception as e:
        print(fields, "FAIL", type(e).__name__, str(e)[:120])
