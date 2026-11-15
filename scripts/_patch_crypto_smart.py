# -*- coding: utf-8 -*-
path = "bp_ingest/crypto_futures.py"
s = open(path, encoding="utf-8").read()

# 1) 常量 + 白名单
s = s.replace('FUNDING_RATE = "/fapi/v1/fundingRate"',
'''FUNDING_RATE = "/fapi/v1/fundingRate"
TOP_ACCOUNT = "/futures/data/topLongShortAccountRatio"
TOP_POSITION = "/futures/data/topLongShortPositionRatio"''')
s = s.replace('    FUNDING_RATE,', '    FUNDING_RATE,\n    TOP_ACCOUNT,\n    TOP_POSITION,')

# 2) _parse_snapshot 增加大户参数与字段
s = s.replace("""def _parse_snapshot(
    contract_code: str,
    premium_index: Any,
    open_interest: Any,
    long_short: Any,
    taker: Any,
    oi_hist: Any,
) -> Optional[dict[str, Any]]:""",
"""def _parse_snapshot(
    contract_code: str,
    premium_index: Any,
    open_interest: Any,
    long_short: Any,
    taker: Any,
    oi_hist: Any,
    top_account: Any = None,
    top_position: Any = None,
) -> Optional[dict[str, Any]]:""")
s = s.replace("""        "basis_pct": basis_pct,
    }""",
"""        "basis_pct": basis_pct,
        "top_account_ratio": (
            _to_float(_latest_item(top_account).get("longShortRatio"))
            if _latest_item(top_account)
            else None
        ),
        "top_position_ratio": (
            _to_float(_latest_item(top_position).get("longShortRatio"))
            if _latest_item(top_position)
            else None
        ),
    }""")

# 3) UPSERT SQL + payload
s = s.replace("""    (contract_code, captured_at, mark_price, index_price, oi_contracts,
     oi_notional, long_short_ratio, taker_buy_sell_ratio, basis_pct, provider)
VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)""",
"""    (contract_code, captured_at, mark_price, index_price, oi_contracts,
     oi_notional, long_short_ratio, taker_buy_sell_ratio, basis_pct,
     top_account_ratio, top_position_ratio, provider)
VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)""")
s = s.replace("""    basis_pct = EXCLUDED.basis_pct,
    provider = EXCLUDED.provider""",
"""    basis_pct = EXCLUDED.basis_pct,
    top_account_ratio = EXCLUDED.top_account_ratio,
    top_position_ratio = EXCLUDED.top_position_ratio,
    provider = EXCLUDED.provider""")
s = s.replace("""            r.get("basis_pct"),
            r.get("provider", "binance"),""",
"""            r.get("basis_pct"),
            r.get("top_account_ratio"),
            r.get("top_position_ratio"),
            r.get("provider", "binance"),""")

# 4) _fetch_one_snapshot 增加端点
s = s.replace("""        _safe(
            OI_HIST,
            {"symbol": contract_code, "period": SNAPSHOT_PERIOD, "limit": 1},
        ),
    )""",
"""        _safe(
            OI_HIST,
            {"symbol": contract_code, "period": SNAPSHOT_PERIOD, "limit": 1},
        ),
        _safe(
            TOP_ACCOUNT,
            {"symbol": contract_code, "period": SNAPSHOT_PERIOD, "limit": 1},
        ),
        _safe(
            TOP_POSITION,
            {"symbol": contract_code, "period": SNAPSHOT_PERIOD, "limit": 1},
        ),
    )""")

open(path, "w", encoding="utf-8").write(s)
print("crypto futures patched:", all(k in s for k in ("TOP_ACCOUNT", "top_account_ratio", "top_position_ratio")))
