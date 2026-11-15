# -*- coding: utf-8 -*-
path = "bp_api/quant/basket.py"
s = open(path, encoding="utf-8").read()

# 1) dataclass 增加等权字段
s = s.replace("""    latest_drift: dict = field(default_factory=dict)
    end_optimal_target: dict = field(default_factory=dict)""",
"""    latest_drift: dict = field(default_factory=dict)
    end_optimal_target: dict = field(default_factory=dict)
    equal_weight_nav: pd.Series = field(default_factory=lambda: pd.Series(dtype=float))
    equal_weight_metrics: dict = field(default_factory=dict)""")

# 2) 等权目标函数
s = s.replace("""    k_user = (
        next((k for k, d in enumerate(price_dates) if d >= user_start), len(price_dates))
        if user_start is not None
        else 0
    )""",
"""    def equal_target(end_idx: int) -> pd.Series:
        \"\"\"当前可用资产的等权目标（与优化目标同一可用集合）。\"\"\"
        avail = available_assets(end_idx)
        w = pd.Series(0.0, index=assets)
        if not avail:
            return w
        weight = 1.0 / len(avail)
        for key in avail:
            w[key] = weight
        return w

    k_user = (
        next((k for k, d in enumerate(price_dates) if d >= user_start), len(price_dates))
        if user_start is not None
        else 0
    )""")

# 3) 初始化等权净值
s = s.replace("""    target = opt(k0 - 1)
    w_actual = target.copy()
    last_target = target""",
"""    target = opt(k0 - 1)
    w_actual = target.copy()
    last_target = target
    eq_weights = equal_target(k0 - 1)
    eq_nav = 1.0
    eq_rows: list[dict] = [{"trade_date": effective_start, "nav": 1.0}]""")

# 4) 循环内更新等权净值（放在 rows.append 之前）
s = s.replace("""        rows.append({"trade_date": day, "nav": float(nav), "ret": float(port_ret)})""",
"""        eq_ret = float((eq_weights * r_t).sum())
        eq_nav *= 1.0 + eq_ret
        eq_grown = eq_weights * (1.0 + r_t)
        eq_total = float(eq_grown.sum())
        if eq_total > 0:
            eq_weights = eq_grown / eq_total
        eq_rows.append({"trade_date": day, "nav": float(eq_nav)})
        rows.append({"trade_date": day, "nav": float(nav), "ret": float(port_ret)})""")

# 5) 调仓时等权组合同时再平衡
s = s.replace("""            w_actual = target.copy()
            last_target = target""",
"""            w_actual = target.copy()
            last_target = target
            eq_weights = equal_target(k - 1)""")

# 6) 结束后计算等权指标并返回
s = s.replace("""    nav_series = nav_df["nav"]
    metrics = compute_metrics(nav_series, None, risk_free, trading_days)""",
"""    nav_series = nav_df["nav"]
    metrics = compute_metrics(nav_series, None, risk_free, trading_days)
    eq_series = (
        pd.DataFrame(eq_rows).set_index("trade_date")["nav"].astype(float)
        if eq_rows else pd.Series(dtype=float)
    )
    eq_metrics = compute_metrics(eq_series, None, risk_free, trading_days) if len(eq_series) > 1 else {}""")

s = s.replace("""        metrics=metrics,
        n_obs=int(len(nav_series)),""",
"""        metrics=metrics,
        n_obs=int(len(nav_series)),
        equal_weight_nav=eq_series,
        equal_weight_metrics={k: float(v) for k, v in eq_metrics.items() if isinstance(v, (int, float))},""")

open(path, "w", encoding="utf-8").write(s)
print("quant patched:", all(k in s for k in ("equal_weight_nav", "equal_target", "eq_rows")))
