# -*- coding: utf-8 -*-
# 1) main.py 注册 baskets
mp = "bp_api/main.py"
m = open(mp, encoding="utf-8").read()
if "from . import baskets" not in m:
    m = m.replace("from . import basket\n", "from . import basket, baskets\n")
    m = m.replace("    basket.register_routes(app)\n", "    basket.register_routes(app)\n    baskets.register_routes(app)\n")
open(mp, "w", encoding="utf-8").write(m)
print("main registered:", "baskets.register_routes" in m)

# 2) basket.py 返回等权净值 + 结构化调仓事件
p = "bp_api/basket.py"
s = open(p, encoding="utf-8").read()
s = s.replace("""        weight_rows = _weight_rows(
            pairs, keys, np.array([result.latest_target.get(k, 0.0) for k in keys])
        )
""",
"""        weight_rows = _weight_rows(
            pairs, keys, np.array([result.latest_target.get(k, 0.0) for k in keys])
        )

        eq_nav_rows = [
            {"trade_date": _iso_date(index), "nav": float(value)}
            for index, value in result.equal_weight_nav.items()
        ]

        rebalance_events = []
        for rb in result.rebalances:
            prev = rb.get("prev_weights") or {}
            target_weights = rb.get("target_weights") or {}
            event_assets = []
            for key in sorted(set(prev) | set(target_weights)):
                symbol, source = _split_key(str(key))
                before = float(prev.get(key, 0.0))
                after = float(target_weights.get(key, 0.0))
                event_assets.append(
                    {
                        "key": key,
                        "symbol": symbol,
                        "source": source,
                        "prev_weight": before,
                        "target_weight": after,
                        "delta": after - before,
                    }
                )
            rebalance_events.append(
                {
                    "trade_date": _iso_date(rb["trade_date"]),
                    "reason": rb.get("reason"),
                    "turnover": float(rb.get("turnover") or 0.0),
                    "max_deviation": float(rb.get("max_deviation") or 0.0),
                    "assets": event_assets,
                }
            )
""")
s = s.replace("""            "nav": nav_rows,
            "annualized_return":""",
"""            "nav": nav_rows,
            "equal_weight_nav": eq_nav_rows,
            "equal_weight_metrics": result.equal_weight_metrics,
            "rebalance_events": rebalance_events,
            "annualized_return":""")
open(p, "w", encoding="utf-8").write(s)
print("basket api patched:", "equal_weight_nav" in s and "rebalance_events" in s)
