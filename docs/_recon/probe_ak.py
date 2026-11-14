# -*- coding: utf-8 -*-
import importlib, traceback
import akshare as ak
print("akshare", ak.__version__)
def try_(name, fn):
    try:
        df = fn()
        print("OK", name, "shape=", getattr(df, "shape", None))
        print("   cols:", list(df.columns)[:14])
        print(df.head(2).to_string()[:600])
    except Exception as e:
        print("FAIL", name, type(e).__name__, str(e)[:200])
try_("stock_zh_index_value_csindex(000300)", lambda: ak.stock_zh_index_value_csindex(symbol="000300"))
try_("index_value_name_funddb", lambda: ak.index_value_name_funddb())
try_("index_value_hist_funddb(000300)", lambda: ak.index_value_hist_funddb(symbol="沪深300", indicator="市盈率"))
try_("stock_zh_a_hist(600519 hfq)", lambda: ak.stock_zh_a_hist(symbol="600519", period="daily", start_date="20250101", end_date="20251114", adjust="hfq"))
try_("stock_index_pe_lg(000300)", lambda: ak.stock_index_pe_lg(symbol="沪深300"))
