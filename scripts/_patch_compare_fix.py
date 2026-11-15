# -*- coding: utf-8 -*-
path = "bp_api/repositories_valuation.py"
s = open(path, encoding="utf-8").read()
old = """    bench_ret = bench.pct_change().dropna()
    frame = pd.DataFrame(rows, columns=["fund_code", "trade_date", "nav"])"""
new = """    frame = pd.DataFrame(rows, columns=["fund_code", "trade_date", "nav"])"""
assert old in s
s = s.replace(old, new)
old2 = """        joined = pd.concat([rets.rename("fund"), bench_ret.rename("bench")], axis=1).dropna()"""
new2 = """        bench_aligned = bench.reindex(series.index, method="ffill")
        bench_ret = bench_aligned.pct_change().dropna()
        joined = pd.concat([rets.rename("fund"), bench_ret.rename("bench")], axis=1).dropna()"""
assert old2 in s
s = s.replace(old2, new2)
open(path, "w", encoding="utf-8").write(s)
print("compare TE alignment fixed")
