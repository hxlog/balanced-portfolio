# -*- coding: utf-8 -*-
path = "bp_api/crypto_futures.py"
s = open(path, encoding="utf-8").read()

# 1) 最新快照 SQL 增加大户列
s = s.replace("""               s.oi_notional, s.long_short_ratio, s.taker_buy_sell_ratio, s.basis_pct""",
"""               s.oi_notional, s.long_short_ratio, s.taker_buy_sell_ratio, s.basis_pct,
               s.top_account_ratio, s.top_position_ratio""")

# 2) contracts 路由：补充资金费率/分位/OI 24h 变化/Smart Money 因子
s = s.replace("""            pct: dict[str, dict] = {}
            for code, metric, window, value, sample, as_of in cur.fetchall():
                pct.setdefault(code, {})[f"{metric}:{window}"] = {
                    "pct": float(value) if value is not None else None,
                    "sample_size": int(sample or 0),
                    "as_of": as_of.isoformat() if as_of else None,
                }
        for row in rows:
            row["percentiles"] = pct.get(row["contract_code"], {})""",
"""            pct: dict[str, dict] = {}
            for code, metric, window, value, sample, as_of in cur.fetchall():
                pct.setdefault(code, {})[f"{metric}:{window}"] = {
                    "pct": float(value) if value is not None else None,
                    "sample_size": int(sample or 0),
                    "as_of": as_of.isoformat() if as_of else None,
                }
            # 资金费率：最新 8h 费率 + 近 30 日分位
            cur.execute(
                \"\"\"
                SELECT DISTINCT ON (contract_code)
                       contract_code, funding_time, funding_rate
                FROM bp_crypto_funding_history
                ORDER BY contract_code, funding_time DESC
                \"\"\"
            )
            funding = {
                code: {"time": ts.isoformat() if ts else None, "rate": float(rate) if rate is not None else None}
                for code, ts, rate in cur.fetchall()
            }
            cur.execute(
                \"\"\"
                SELECT contract_code, min(funding_rate), max(funding_rate),
                       percentile_cont(0.5) WITHIN GROUP (ORDER BY funding_rate)
                FROM bp_crypto_funding_history
                WHERE funding_time >= now() - interval '30 days'
                GROUP BY contract_code
                \"\"\"
            )
            funding_range = {
                code: {"min": float(lo) if lo is not None else None,
                       "max": float(hi) if hi is not None else None,
                       "median": float(mid) if mid is not None else None}
                for code, lo, hi, mid in cur.fetchall()
            }
            # OI 24h 变化
            cur.execute(
                \"\"\"
                SELECT DISTINCT ON (s.contract_code)
                       s.contract_code, s.oi_notional
                FROM bp_crypto_futures_snapshot_5m s
                JOIN bp_crypto_contract c USING (contract_code)
                WHERE c.is_active AND s.captured_at <= now() - interval '24 hours'
                ORDER BY s.contract_code, s.captured_at DESC
                \"\"\"
            )
            oi_prev = {code: float(value) if value is not None else None for code, value in cur.fetchall()}
        for row in rows:
            row["percentiles"] = pct.get(row["contract_code"], {})
            code = row["contract_code"]
            f = funding.get(code) or {}
            row["funding_rate"] = f.get("rate")
            row["funding_time"] = f.get("time")
            info = funding_range.get(code) or {}
            if f.get("rate") is not None and info.get("min") is not None and info.get("max") is not None:
                span = info["max"] - info["min"]
                row["funding_percentile_30d"] = (
                    round((f["rate"] - info["min"]) / span * 100, 1) if span > 0 else 50.0
                )
            else:
                row["funding_percentile_30d"] = None
            prev = oi_prev.get(code)
            if prev and row.get("oi_notional"):
                row["oi_change_24h_pct"] = round((row["oi_notional"] / prev - 1) * 100, 2)
            else:
                row["oi_change_24h_pct"] = None
            top_pos = row.get("top_position_ratio")
            global_lsr = row.get("long_short_ratio")
            row["smart_money_divergence"] = (
                round(float(top_pos) - float(global_lsr), 4)
                if top_pos is not None and global_lsr is not None else None
            )""")

# 3) summary：新增字段，保留兼容
s = s.replace("""        latest_at = max((r["captured_at"] for r in rows if r["captured_at"]), default=None)
        payload = _envelope(
            {
                "contracts": len(rows),
                "total_oi_notional": total_oi,
                "weighted_long_short_ratio": weighted_ls,
                "median_taker_buy_sell_ratio": median_taker,
                "latest_captured_at": latest_at.isoformat() if latest_at else None,
            },
            rows=len(rows),
        )""",
"""        latest_at = max((r["captured_at"] for r in rows if r["captured_at"]), default=None)
        with db.get_conn() as conn, conn.cursor() as cur:
            cur.execute(
                "SELECT DISTINCT ON (contract_code) contract_code, funding_rate"
                " FROM bp_crypto_funding_history ORDER BY contract_code, funding_time DESC"
            )
            funding_rows = cur.fetchall()
            cur.execute(
                "SELECT DISTINCT ON (s.contract_code) s.contract_code, s.oi_notional"
                " FROM bp_crypto_futures_snapshot_5m s"
                " JOIN bp_crypto_contract c USING (contract_code)"
                " WHERE c.is_active AND s.captured_at <= now() - interval '24 hours'"
                " ORDER BY s.contract_code, s.captured_at DESC"
            )
            oi_prev_rows = dict(cur.fetchall())
        funding_by_code = {code: float(rate) for code, rate in funding_rows if rate is not None}
        funding_values = [funding_by_code.get(r["contract_code"]) for r in rows]
        funding_values = [v for v in funding_values if v is not None]
        oi_total_prev = sum(
            oi_prev_rows.get(r["contract_code"]) or 0 for r in rows
        )
        total_oi_change = None
        if oi_total_prev > 0:
            total_oi_change = round((total_oi / oi_total_prev - 1) * 100, 2)
        top_values = [float(r["top_position_ratio"]) for r in rows if r.get("top_position_ratio") is not None]
        smart_div = None
        if total_oi > 0:
            weighted_top = sum((r["oi_notional"] or 0) * float(r["top_position_ratio"]) for r in rows if r.get("top_position_ratio") is not None)
            weights_sum = sum((r["oi_notional"] or 0) for r in rows if r.get("top_position_ratio") is not None)
            if weights_sum > 0:
                smart_div = round(weighted_top / weights_sum - (weighted_ls or 1), 4)
        payload = _envelope(
            {
                "contracts": len(rows),
                "contracts_with_top_data": len(top_values),
                "total_oi_notional": total_oi,
                "total_oi_change_24h_pct": total_oi_change,
                "weighted_long_short_ratio": weighted_ls,
                "weighted_long_short_basis": "account",
                "weighted_long_short_note": "按 OI 名义值加权 · 全市场多空账户数比",
                "median_taker_buy_sell_ratio": median_taker,
                "weighted_funding_rate": (round(sum(funding_values) / len(funding_values), 8) if funding_values else None),
                "smart_money_divergence": smart_div,
                "latest_captured_at": latest_at.isoformat() if latest_at else None,
            },
            rows=len(rows),
        )""")

# 4) series 增加大户比
s = s.replace("""                SELECT captured_at, mark_price, oi_notional, long_short_ratio,
                       taker_buy_sell_ratio, basis_pct""",
"""                SELECT captured_at, mark_price, oi_notional, long_short_ratio,
                       taker_buy_sell_ratio, basis_pct, top_account_ratio, top_position_ratio""")

open(path, "w", encoding="utf-8").write(s)
print("api patched:", all(k in s for k in ("smart_money_divergence", "funding_percentile_30d", "total_oi_change_24h_pct")))
