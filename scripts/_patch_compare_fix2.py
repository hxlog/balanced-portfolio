# -*- coding: utf-8 -*-
path = "bp_api/repositories_valuation.py"
s = open(path, encoding="utf-8").read()
old = """    bench = pd.Series(
        [float(row[2]) for row in bench_rows if row[2] is not None],
        index=pd.to_datetime([row[1] for row in bench_rows if row[2] is not None]),
    ).sort_index()"""
new = """    bench_map: dict = {}
    for row in bench_rows:
        if row[2] is None:
            continue
        bench_map[pd.Timestamp(row[1])] = float(row[2])
    bench = pd.Series(bench_map).sort_index()"""
assert old in s, "bench build missing"
s = s.replace(old, new)
open(path, "w", encoding="utf-8").write(s)
print("bench dedupe fixed")
