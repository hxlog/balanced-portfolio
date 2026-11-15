import sys, time
sys.stdout.reconfigure(encoding="utf-8")
import akshare as ak
t0 = time.time()
try:
    df = ak.stock_info_a_code_name()
    print("stock list:", len(df), "sample:", df.head(2).to_dict("records"), "%.1fs" % (time.time()-t0))
except Exception as exc:
    print("stock list FAIL", type(exc).__name__, str(exc)[:120])
try:
    t1 = time.time()
    hist = ak.stock_zh_a_hist(symbol="600519", period="daily", start_date="20240101", end_date="20261114", adjust="hfq")
    print("hist rows:", len(hist), "cols:", list(hist.columns)[:6], "%.1fs" % (time.time()-t1))
except Exception as exc:
    print("hist FAIL", type(exc).__name__, str(exc)[:120])
