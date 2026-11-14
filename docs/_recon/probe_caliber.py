# -*- coding: utf-8 -*-
import sys
sys.stdout.reconfigure(encoding="utf-8")
import akshare as ak

def show(name, fn):
    try:
        df = fn()
        print(f"[OK] {name} rows={len(df)} cols={list(df.columns)}", flush=True)
        print(df.tail(3).to_string()[:900], flush=True)
        return df
    except Exception as e:
        print(f"[FAIL] {name} {type(e).__name__}: {str(e)[:120]}", flush=True)

show("legu PE 中证中药", lambda: ak.stock_index_pe_lg(symbol="中证中药"))
show("legu PB 中证中药", lambda: ak.stock_index_pb_lg(symbol="中证中药"))
show("csindex 930641", lambda: ak.stock_zh_index_value_csindex(symbol="930641"))
