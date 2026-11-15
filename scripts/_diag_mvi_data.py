import sys
sys.path.insert(0, "/opt/balanced-portfolio")
sys.stdout.reconfigure(encoding="utf-8")
import pandas as pd
from bp_ingest.config import load_config
from bp_ingest.db import connect
cfg = load_config()
with connect(cfg.db) as conn:
    for code in ["000016","000300","000510","000905","000852"]:
        df = pd.read_sql("select trade_date, pe_ttm, pb, dividend_yield_ttm, erp, roe_ttm from bp_index_valuation_daily where index_code=%s and is_primary order by trade_date", conn, params=(code,))
        print(code, "rows", len(df), "dates", df["trade_date"].min(), "->", df["trade_date"].max(),
              "nulls", {c: int(df[c].isna().sum()) for c in ("pe_ttm","pb","dividend_yield_ttm","erp","roe_ttm")})
    q = pd.read_sql("select trade_date, count(*) n from bp_index_quote_daily where symbol='000300' and adjust='bfq' group by trade_date having count(*)>1", conn)
    print("dup quote dates:", len(q))
