# -*- coding: utf-8 -*-
import sys, time
sys.path.insert(0, "/opt/balanced-portfolio")
sys.stdout.reconfigure(encoding="utf-8")
import akshare as ak
t0 = time.time()
try:
    info = ak.sw_index_first_info()
    print("sw first info:", len(info), list(info.columns)[:8], round(time.time()-t0,1))
    print(info.head(2).to_string()[:300])
except Exception as e:
    print("FAIL sw_index_first_info", type(e).__name__, str(e)[:200])
try:
    comp = ak.index_component_sw(symbol="801010")
    print("component:", len(comp), list(comp.columns)[:6], round(time.time()-t0,1))
    print(comp.head(2).to_string()[:300])
except Exception as e:
    print("FAIL index_component_sw", type(e).__name__, str(e)[:200])
