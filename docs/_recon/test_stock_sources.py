# -*- coding: utf-8 -*-
import sys, socket, time
sys.path.insert(0, "/opt/balanced-portfolio")
sys.stdout.reconfigure(encoding="utf-8")

print("--- socket baostock:10030 ---")
try:
    s = socket.create_connection(("www.baostock.com", 10030), timeout=8)
    print("connect ok")
    s.close()
except Exception as e:
    print("FAIL", type(e).__name__, str(e)[:120])

print("--- akshare sina daily ---")
try:
    import akshare as ak
    t0 = time.time()
    df = ak.stock_zh_a_daily(symbol="sh600036", start_date="20240101", end_date="20241114", adjust="hfq")
    print("sina hfq rows:", len(df), "cols:", list(df.columns)[:8], round(time.time()-t0, 1))
except Exception as e:
    print("FAIL sina", type(e).__name__, str(e)[:150])

print("--- akshare tencent ---")
try:
    t0 = time.time()
    df2 = ak.stock_zh_a_hist_tx(symbol="sh600036", start_date="20240101", end_date="20241114", adjust="hfq")
    print("tx rows:", len(df2), list(df2.columns)[:8], round(time.time()-t0, 1))
except Exception as e:
    print("FAIL tx", type(e).__name__, str(e)[:150])
