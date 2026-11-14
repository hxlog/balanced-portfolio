# -*- coding: utf-8 -*-
import sys
sys.stdout.reconfigure(encoding="utf-8")
import time
t0 = time.time()
try:
    import akshare as ak
    df = ak.stock_zh_a_spot_em()
    print("rows:", len(df), "cols:", [c for c in df.columns][:12], "took:", round(time.time()-t0,1))
    for col in ["市盈率-动态", "市净率", "总市值"]:
        if col in df.columns:
            print(col, "non-null:", int(df[col].notna().sum()))
except Exception as e:
    print("FAIL", type(e).__name__, str(e)[:200], "took:", round(time.time()-t0,1))
