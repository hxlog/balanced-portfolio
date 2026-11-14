# -*- coding: utf-8 -*-
import sys
sys.stdout.reconfigure(encoding="utf-8")
import time
from bp_ingest.http_session import install_hardened_session
install_hardened_session()
t0 = time.time()
try:
    import akshare as ak
    df = ak.stock_zh_a_spot_em()
    print("OK rows:", len(df), "took:", round(time.time()-t0,1))
    print("cols:", [c for c in df.columns][:14])
except Exception as e:
    print("FAIL", type(e).__name__, str(e)[:200], round(time.time()-t0,1))
