# -*- coding: utf-8 -*-
"""为全部估值指数补齐行情配置（一次性回填用）。

背景：/valuation 的 521 只指数中只有 61 只有行情（bp_quote_clean），
导致「收盘/当日/7日/52周」列大面积为空。本脚本：
  1. 按 market 选择数据源（A 股 -> cn_index_em；HK -> hk_index_em；US/GLobal -> global_index_em 用中文名）；
  2. 为缺配置的指数插入 bp_index_config（is_selectable=true，category=index，adjust=bfq）；
  3. 输出待回填 symbol 列表供 ingest 使用。
"""
import sys
sys.path.insert(0, "/opt/balanced-portfolio")
sys.stdout.reconfigure(encoding="utf-8")
from bp_ingest.config import load_config
from bp_ingest.db import connect

SOURCE_BY_MARKET = {
    "CSI": "cn_index_em",
    "SH": "cn_index_em",
    "SZ": "cn_index_em",
    "CNI": "cn_index_em",
    "BJ": "cn_index_em",
    "HK": "hk_index_em",
    "US": "global_index_em",
    "GLOBAL": "global_index_em",
}

app = load_config()
with connect(app.db) as conn, conn.cursor() as cur:
    cur.execute("select index_code, name, market from bp_index_master where is_tracked order by index_code")
    rows = cur.fetchall()
    cur.execute("select symbol, source from bp_index_config where is_deleted = 0")
    existing = set(cur.fetchall())
    inserted = 0
    targets = []
    for code, name, market in rows:
        source = SOURCE_BY_MARKET.get(market)
        if source is None:
            continue
        symbol = name if source == "global_index_em" else code
        if (symbol, source) in existing:
            targets.append(symbol)
            continue
        cur.execute(
            """INSERT INTO bp_index_config
                 (symbol, source, category, name, adjust, adjust_modes,
                  is_selectable, is_deleted, index_code)
               VALUES (%s, %s, %s, %s, %s, %s, TRUE, 0, %s)
               ON CONFLICT (symbol, source) DO UPDATE SET
                 is_deleted = 0, index_code = EXCLUDED.index_code, updated_at = now()""",
            (symbol, source, "index", name, "bfq", ["bfq"], code),
        )
        inserted += 1
        targets.append(symbol)
    conn.commit()
print("indices:", len(rows), "configs inserted:", inserted, "targets:", len(targets))
print("sample:", targets[:8])
with open("/tmp/valuation_symbols.txt", "w", encoding="utf-8") as f:
    f.write("\n".join(targets))
print("written /tmp/valuation_symbols.txt")
