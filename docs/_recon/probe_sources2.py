# -*- coding: utf-8 -*-
import sys, time, traceback
sys.stdout.reconfigure(encoding="utf-8")
import akshare as ak

def probe(name, fn, max_rows=3):
    t0 = time.time()
    try:
        df = fn()
        cols = list(df.columns)
        print(f"[OK] {name} rows={len(df)} cols={len(cols)} {time.time()-t0:.1f}s", flush=True)
        print("   columns:", cols, flush=True)
        print(df.head(max_rows).to_string()[:800], flush=True)
        if "日期" in df.columns:
            print("   date range:", df["日期"].min(), "→", df["日期"].max(), flush=True)
    except Exception as e:
        print(f"[FAIL] {name} {type(e).__name__}: {str(e)[:160]} ({time.time()-t0:.1f}s)", flush=True)

probe("csindex valuation 930641", lambda: ak.stock_zh_index_value_csindex(symbol="930641"))
probe("legu index pe 中证500", lambda: ak.stock_index_pe_lg(symbol="中证500"))
probe("em all-A spot", lambda: ak.stock_zh_a_spot_em())
probe("em etf spot", lambda: ak.fund_etf_spot_em())
probe("bond 10y", lambda: ak.bond_zh_us_rate(start_date="20150101"))
probe("sw level1", lambda: ak.sw_index_first_info())
probe("em index hist 930641", lambda: ak.index_zh_a_hist(symbol="930641", period="daily", start_date="20250101", end_date="20251114"))
