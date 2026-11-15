import re
path = "scripts/research_mvi.py"
s = open(path, encoding="utf-8").read()

new_loader = '''def load_panel(conn) -> pd.DataFrame:
    """5 大宽基的周频估值面板 → 滚动分位因子（跨宽基等权平均）。"""
    factor_frames: dict[str, list[pd.Series]] = {f: [] for f in FACTORS}
    for code in PROXIES:
        query = """
            SELECT trade_date, metric, value
            FROM bp_index_valuation_series
            WHERE index_code = %s AND trade_date >= DATE '2015-01-01'
              AND metric IN ('pe_ttm', 'pb', 'dividend_yield_ttm', 'erp')
        """
        df = pd.read_sql(query, conn, params=(code,))
        if df.empty:
            continue
        df["trade_date"] = pd.to_datetime(df["trade_date"])
        wide = df.pivot_table(index="trade_date", columns="metric", values="value", aggfunc="last").sort_index()
        wide = wide.apply(pd.to_numeric, errors="coerce")
        if "pe_ttm" not in wide or "pb" not in wide:
            continue
        wide = wide[wide["pe_ttm"].notna() & wide["pb"].notna()]
        wide["roe_ttm"] = wide["pb"] / wide["pe_ttm"] * 100.0
        for factor, col, invert in [
            ("cheap_pe", "pe_ttm", True), ("cheap_pb", "pb", True),
            ("div_pct", "dividend_yield_ttm", False), ("erp_pct", "erp", False),
            ("roe_pct", "roe_ttm", False),
        ]:
            series = wide[col].astype(float)
            pct = rolling_percentile(series, ROLL_WEEKS, MIN_WEEKS)
            if invert:
                pct = 100.0 - pct
            factor_frames[factor].append(pct.rename("p"))
    combined = {}
    for factor, frames in factor_frames.items():
        if not frames:
            continue
        combined[factor] = pd.concat(frames, axis=1).mean(axis=1, skipna=True)
    panel = pd.DataFrame(combined).sort_index()
    panel = panel.dropna(subset=["cheap_pe", "cheap_pb"])
    return panel
'''

start = s.find("def load_panel(conn) -> pd.DataFrame:")
end = s.find("def load_forward_return(conn) -> pd.Series:")
assert start != -1 and end != -1, (start, end)
s = s[:start] + new_loader + "\n\n" + s[end:]

# 前向收益去重
s = s.replace(
    'df = df.set_index("trade_date").sort_index()\n    close = df["close"].astype(float)',
    'df = df.drop_duplicates(subset=["trade_date"], keep="last")\n    df = df.set_index("trade_date").sort_index()\n    close = pd.to_numeric(df["close"], errors="coerce")'
)
open(path, "w", encoding="utf-8").write(s)
print("loader replaced, len:", len(s))
