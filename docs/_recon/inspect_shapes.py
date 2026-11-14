# -*- coding: utf-8 -*-
import sys, json, pathlib
sys.stdout.reconfigure(encoding="utf-8")
sys.path.insert(0, str(pathlib.Path(".").resolve()))
from bp_ingest.valuation_pingan import normalize_index_row
row = json.loads(pathlib.Path("bp_api/tests/fixtures/pingan/index_data_v2_930641.json").read_text(encoding="utf-8"))
if isinstance(row, list): row = row[0]
n = normalize_index_row(row)
for k in ["index_code","market","name","stock_list","etf_fund","otc_fund","pe_ttm","dividend_yield_ttm"]:
    v = n.get(k)
    print(k, "=", str(v)[:300])
f = json.loads(pathlib.Path("bp_api/tests/fixtures/pingan/tracker_funds.json").read_text(encoding="utf-8"))
print("tracker type:", type(f).__name__)
row0 = f[0] if isinstance(f, list) else f
print("tracker keys:", list(row0.keys())[:25] if isinstance(row0, dict) else row0)
print("sample:", json.dumps(row0, ensure_ascii=False)[:600])
