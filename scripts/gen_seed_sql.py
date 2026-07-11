"""从 validated_candidates.json 生成可审阅的资产种子 SQL。

用法:
  python scripts/gen_seed_sql.py validated_candidates.json > asset_seed.sql
"""
from __future__ import annotations

import json
import sys

# 现有 (symbol, source) 集合 — 安全过滤, 防重复
EXISTING = set()
for sym, src in [
    ("000510", "cn_index_sina"), ("000688", "cn_index_sina"),
    ("000852", "cn_index_sina"), ("000905", "cn_index_sina"),
    ("HSI", "hk_index_em"),
    ("标普500", "global_index_em"), ("纳斯达克100", "global_index_em"),
    ("日经225", "global_index_sina"), ("日经225", "global_index_em"),
    ("CU0", "cmdty_main_sina"), ("M0", "cmdty_main_sina"),
    ("MA0", "cmdty_main_sina"), ("SC0", "cmdty_main_sina"),
    ("0-3Y", "bond_csi_treasury"), ("10Y", "bond_csi_treasury"),
    ("30Y", "bond_csi_treasury"),
    ("159399", "etf_sina"), ("159915", "etf_sina"), ("159920", "etf_sina"),
    ("510050", "etf_sina"), ("510300", "etf_sina"), ("511090", "etf_sina"),
    ("511260", "etf_sina"), ("511580", "etf_sina"), ("513000", "etf_sina"),
    ("513100", "etf_sina"), ("513500", "etf_sina"), ("513530", "etf_sina"),
    ("513630", "etf_sina"), ("518880", "etf_sina"), ("518880", "etf_em"),
    ("561580", "etf_sina"),
]:
    EXISTING.add((sym, src))


def sql_str(s: str) -> str:
    return "'" + s.replace("'", "''") + "'"


def sql_jsonb(d: dict) -> str:
    return "'" + json.dumps(d, ensure_ascii=False) + "'::jsonb"


def main():
    with open(sys.argv[1], encoding="utf-8") as f:
        rows = json.load(f)

    # 过滤现有 + 去重
    seen = set()
    clean = []
    for r in rows:
        sym = r["symbol"]
        src = r["source"]
        if (sym, src) in EXISTING:
            continue
        if (sym, src) in seen:
            continue
        seen.add((sym, src))
        clean.append(r)

    # 按 source 分组便于阅读
    order = ["cn_index_em", "etf_em", "hk_index_em", "global_index_em",
             "cmdty_main_sina", "bond_csi_treasury"]
    clean.sort(key=lambda r: (order.index(r["source"]) if r["source"] in order else 99,
                              r["category"], r["symbol"]))

    out = []
    out.append("-- Generated asset seed candidates")
    out.append("-- 批量扩充资产池: A股指数/ETF/港股/全球指数/商品主力/国债期限")
    out.append("-- 幂等: ON CONFLICT 刷新元数据, 保留 start_date(ingest 回写)")
    out.append("-- 生成自 validated_candidates.json (akshare 枚举校验通过)")
    out.append("")
    out.append("INSERT INTO bp_index_config (symbol, source, category, name, extra_params) VALUES")

    lines = []
    for r in clean:
        lines.append(
            f"    ({sql_str(r['symbol'])}, {sql_str(r['source'])}, "
            f"{sql_str(r['category'])}, {sql_str(r['name'])}, "
            f"{sql_jsonb(r.get('extra_params') or {})})"
        )
    out.append(",\n".join(lines))

    out.append("ON CONFLICT (symbol, source) DO UPDATE SET")
    out.append("    category     = EXCLUDED.category,")
    out.append("    name         = EXCLUDED.name,")
    out.append("    extra_params = EXCLUDED.extra_params,")
    out.append("    is_deleted   = 0;")
    out.append("")

    sys.stdout.write("\n".join(out))
    print(f"\n-- 共 {len(clean)} 行 (已剔除 {len(rows)-len(clean)} 现有/重复)", file=sys.stderr)


if __name__ == "__main__":
    main()
