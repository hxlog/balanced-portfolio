# -*- coding: utf-8 -*-
path = "bp_api/repositories_valuation.py"
s = open(path, encoding="utf-8").read()
marker = "def get_index_benchmark_stats("
assert marker in s
func = '''def compare_funds(
    conn: psycopg.Connection,
    fund_codes: list[str],
    start: date | None = None,
    end: date | None = None,
    benchmark_code: str = "000300",
) -> dict:
    """基金对比：区间总收益/年化收益/波动/最大回撤 + 相对基准的跟踪误差与信息比率。"""
    import math

    if not fund_codes:
        return {"start": None, "end": None, "benchmark_code": benchmark_code, "items": []}
    end = end or date.today()
    start = start or date(end.year, 1, 1)
    with conn.cursor() as cur:
        cur.execute(
            "SELECT fund_code, trade_date, nav FROM bp_fund_nav_daily"
            " WHERE fund_code = ANY(%s) AND trade_date BETWEEN %s AND %s"
            " ORDER BY fund_code, trade_date",
            (fund_codes, start, end),
        )
        rows = cur.fetchall()
        cur.execute(
            "SELECT fund_code, name, fund_scale FROM bp_fund_master WHERE fund_code = ANY(%s)",
            (fund_codes,),
        )
        meta = {row[0]: {"name": row[1], "fund_scale": row[2]} for row in cur.fetchall()}
        cur.execute(
            "SELECT symbol, trade_date, close FROM bp_index_quote_daily"
            " WHERE symbol = %s AND adjust = 'bfq' AND trade_date BETWEEN %s AND %s ORDER BY trade_date",
            (benchmark_code, start, end),
        )
        bench_rows = cur.fetchall()
    bench = pd.Series(
        [float(row[2]) for row in bench_rows if row[2] is not None],
        index=pd.to_datetime([row[1] for row in bench_rows if row[2] is not None]),
    ).sort_index()
    bench_ret = bench.pct_change().dropna()
    frame = pd.DataFrame(rows, columns=["fund_code", "trade_date", "nav"])
    items = []
    for fund_code, part in frame.groupby("fund_code"):
        series = pd.Series(
            pd.to_numeric(part["nav"], errors="coerce").to_numpy(),
            index=pd.to_datetime(part["trade_date"]),
        ).dropna().sort_index()
        if len(series) < 5:
            continue
        total = float(series.iloc[-1] / series.iloc[0] - 1)
        days = max((series.index[-1] - series.index[0]).days, 1)
        ann = (1 + total) ** (365.0 / days) - 1
        rets = series.pct_change().dropna()
        vol = float(rets.std() * math.sqrt(252))
        cummax = series.cummax()
        mdd = float((series / cummax - 1).min())
        item = {
            "fund_code": fund_code,
            "name": (meta.get(fund_code) or {}).get("name"),
            "fund_scale": float((meta.get(fund_code) or {}).get("fund_scale")) if (meta.get(fund_code) or {}).get("fund_scale") is not None else None,
            "start": str(series.index[0].date()),
            "end": str(series.index[-1].date()),
            "n_obs": int(len(series)),
            "total_return_pct": round(total * 100, 4),
            "ann_return_pct": None if days < 30 else round(ann * 100, 4),
            "ann_vol_pct": round(vol * 100, 4),
            "max_dd_pct": round(mdd * 100, 4),
        }
        joined = pd.concat([rets.rename("fund"), bench_ret.rename("bench")], axis=1).dropna()
        if len(joined) > 20:
            diff = joined["fund"] - joined["bench"]
            te = float(diff.std() * math.sqrt(252))
            bench_total = float((1 + joined["bench"]).prod())
            bench_ann = bench_total ** (365.0 / max(days, 1)) - 1 if days else None
            item["tracking_error_pct"] = round(te * 100, 4)
            item["info_ratio"] = round((ann - bench_ann) / te, 4) if te > 1e-9 and bench_ann is not None else None
            item["excess_return_pct"] = round((total - (bench_total - 1)) * 100, 4)
        else:
            item["tracking_error_pct"] = None
            item["info_ratio"] = None
            item["excess_return_pct"] = None
        items.append(item)
    items.sort(key=lambda row: row["total_return_pct"], reverse=True)
    return {
        "start": str(start),
        "end": str(end),
        "benchmark_code": benchmark_code,
        "items": items,
    }


'''
s = s.replace(marker, func + marker, 1)
open(path, "w", encoding="utf-8").write(s)
print("inserted compare_funds")
