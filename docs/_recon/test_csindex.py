# -*- coding: utf-8 -*-
import sys, time
sys.stdout.reconfigure(encoding="utf-8")
t0 = time.time()
try:
    import akshare as ak
    df = ak.stock_zh_index_value_csindex(symbol="930641")
    print("rows:", len(df), "cols:", list(df.columns), "took:", round(time.time()-t0,1))
    print(df.tail(2).to_string())
except Exception as e:
    print("FAIL", type(e).__name__, str(e)[:300], round(time.time()-t0,1))
