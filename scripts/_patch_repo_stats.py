# -*- coding: utf-8 -*-
path = "bp_api/repositories_valuation.py"
s = open(path, encoding="utf-8").read()
marker = "def upsert_market_valuation_index("
assert marker in s, "marker missing"

func = '''def get_index_benchmark_stats(
    conn: psycopg.Connection, index_code: str, benchmark_code: str = "000300"
) -> dict:
    """指数 vs 基准的日收益描述统计（直方图 + Beta + 相关系数）。"""
    import math

    with conn.cursor() as cur:
        cur.execute(
            "SELECT symbol, trade_date, close FROM bp_index_quote_daily"
            " WHERE symbol IN (%s, %s) AND adjust = 'bfq' ORDER BY symbol, trade_date",
            (index_code, benchmark_code),
        )
        rows = cur.fetchall()
        cur.execute("SELECT name FROM bp_index_master WHERE index_code = %s", (benchmark_code,))
        name_row = cur.fetchone()
    if not rows:
        return {}
    frame = pd.DataFrame(rows, columns=["symbol", "trade_date", "close"])
    frame["trade_date"] = pd.to_datetime(frame["trade_date"])
    frame["close"] = pd.to_numeric(frame["close"], errors="coerce")
    frame = frame.drop_duplicates(subset=["symbol", "trade_date"], keep="last")
    wide = frame.pivot(index="trade_date", columns="symbol", values="close").dropna()
    if index_code not in wide or benchmark_code not in wide or len(wide) < 60:
        return {}
    rets = wide.pct_change().dropna()
    target = rets[index_code]
    bench = rets[benchmark_code]
    tail = rets.iloc[-757:] if len(rets) > 757 else rets
    vol = float(tail[index_code].std() * math.sqrt(252))
    beta = None
    if len(tail) > 5:
        cov = float(np.cov(tail[index_code], tail[benchmark_code])[0][1])
        var = float(np.var(tail[benchmark_code], ddof=1))
        beta = cov / var if var > 1e-12 else None
    pearson = float(tail[index_code].corr(tail[benchmark_code]))
    rank_idx = tail[index_code].rank()
    rank_bench = tail[benchmark_code].rank()
    spearman = float(rank_idx.corr(rank_bench))
    window = target.iloc[-252:] if len(target) > 252 else target
    if len(window) > 10:
        counts, bins = np.histogram(window.to_numpy() * 100, bins=30)
        histogram = [
            {"bin": round(float((bins[i] + bins[i + 1]) / 2), 3), "count": int(counts[i])}
            for i in range(len(counts))
        ]
    else:
        histogram = []
    mean = float(window.mean() * 100)
    std = float(window.std() * 100)
    skew = None
    kurt = None
    if len(window) > 2 and std > 1e-12:
        skew = float((((window - window.mean()) ** 3).mean()) / ((window.std()) ** 3))
    if len(window) > 3 and std > 1e-12:
        kurt = float((((window - window.mean()) ** 4).mean()) / ((window.std()) ** 4) - 3)
    return {
        "index_code": index_code,
        "benchmark_code": benchmark_code,
        "benchmark_name": name_row[0] if name_row else benchmark_code,
        "as_of": str(wide.index[-1].date()),
        "n_obs": int(len(window)),
        "ann_vol": round(vol * 100, 4),
        "beta": None if beta is None else round(beta, 4),
        "pearson": round(pearson, 4),
        "spearman": round(spearman, 4),
        "mean_daily_pct": round(mean, 4),
        "std_daily_pct": round(std, 4),
        "skew": None if skew is None else round(skew, 3),
        "kurtosis": None if kurt is None else round(kurt, 3),
        "histogram": histogram,
    }


'''
s = s.replace(marker, func + marker, 1)
open(path, "w", encoding="utf-8").write(s)
print("inserted benchmark stats")
