# -*- coding: utf-8 -*-
import sys, json, pathlib
sys.stdout.reconfigure(encoding="utf-8")
sys.path.insert(0, str(pathlib.Path(".").resolve()))
from bp_ingest.valuation_pingan import normalize_index_row
raw = json.loads(pathlib.Path("bp_api/tests/fixtures/pingan/index_data_v2_930641.json").read_text(encoding="utf-8"))
print("top keys:", list(raw.keys())[:8] if isinstance(raw, dict) else type(raw))
row = raw["rows"][0] if isinstance(raw, dict) and "rows" in raw else (raw[0] if isinstance(raw, list) else raw)
n = normalize_index_row(row)
for k in ["index_code","market","name","stock_list","etf_fund","otc_fund","pe_ttm","dividend_yield_ttm","profit_trace","roe_trace"]:
    print(k, "=", str(n.get(k))[:260])
