# -*- coding: utf-8 -*-
"""把统一 ETL 的 v3 资产（A股/港股/ETF）桥接进 bp_index_config，供清洗/回测/构建器复用。

背景：回测面板只读 bp_quote_clean（key = symbol@source）；v3 行情在
bp_stock_quote_daily / bp_etf_quote_daily。桥接做法：
  - 为每只 v3 资产生成一条 managed_by='bp_etl' 的配置（source=etl_a_stock/etl_hk_stock/etl_etf，
    adjust='hfq'，adjust_modes={bfq,hfq}，currency=CNY/HKD/CNY）；
  - cleaning 对本类 source 从 v3 表读原始价，按既有口径（日历/插值/港股CNY折算）写 bp_quote_clean；
  - 回测/构建器无感读取（symbol@etl_*）。

用法：
  python scripts/seed_etl_assets.py --dry-run          # 预演（默认）
  python scripts/seed_etl_assets.py --apply            # 真正写入
  python scripts/seed_etl_assets.py --apply --selectable false --kinds a_stock
"""
from __future__ import annotations

import argparse
import os
import sys

import psycopg

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, REPO)
sys.stdout.reconfigure(encoding="utf-8")


def load_env() -> dict:
    values = {}
    path = os.path.join(REPO, ".env")
    if not os.path.exists(path):
        return values
    for line in open(path, encoding="utf-8"):
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        values[key.strip()] = value.split(" #")[0].strip().strip('"').strip("'")
    return values


DB_HOST = os.getenv("BP_ETL_DB_HOST") or "81.71.158.239"


def db_conn():
    env = load_env()
    conn = psycopg.connect(
        host=DB_HOST, port=int(env.get("PGPORT", "5432")),
        dbname=env.get("PGDATABASE", "postgres"), user=env.get("PGUSER", "postgres"),
        password=env.get("PGPASSWORD", ""),
    )
    return conn


KIND_SQL: dict[str, tuple[str, str, str, str]] = {
    # kind: (source, category, currency, SELECT 列)
    "a_stock": (
        "etl_a_stock",
        "stock",
        "CNY",
        "SELECT stock_code AS code, name FROM bp_stock_master"
        " WHERE market IN ('SH','SZ','BJ') AND is_delisted = FALSE",
    ),
    "hk_stock": (
        "etl_hk_stock",
        "stock",
        "HKD",
        "SELECT stock_code AS code, name FROM bp_stock_master"
        " WHERE market = 'HK' AND is_delisted = FALSE",
    ),
    "etf": (
        "etl_etf",
        "etf",
        "CNY",
        "SELECT etf_code AS code, name FROM bp_etf_master",
    ),
}

UPSERT_SQL = (
    "INSERT INTO bp_index_config"
    " (symbol, source, category, name, start_date, extra_params, is_deleted,"
    "  adjust, adjust_modes, is_selectable, currency, managed_by)"
    " VALUES (%s, %s, %s, %s, NULL, '{}'::jsonb, 0, 'hfq', ARRAY['bfq','hfq'], %s, %s, 'bp_etl')"
    " ON CONFLICT (symbol, source) DO UPDATE SET"
    "  category = EXCLUDED.category, name = EXCLUDED.name,"
    "  adjust = EXCLUDED.adjust, adjust_modes = EXCLUDED.adjust_modes,"
    "  is_deleted = 0, is_selectable = EXCLUDED.is_selectable,"
    "  currency = EXCLUDED.currency, managed_by = 'bp_etl', updated_at = now()"
)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--kinds", default="a_stock,hk_stock,etf")
    parser.add_argument("--apply", action="store_true", help="真正写入（默认 dry-run）")
    parser.add_argument("--selectable", choices=["true", "false"], default="true")
    args = parser.parse_args()
    kinds = [item.strip() for item in args.kinds.split(",") if item.strip()]
    unknown = [k for k in kinds if k not in KIND_SQL]
    if unknown:
        print(f"未知 kind: {unknown}（可选 {sorted(KIND_SQL)}）")
        return 2
    selectable = args.selectable == "true"
    conn = db_conn()
    total = 0
    try:
        with conn.cursor() as cur:
            for kind in kinds:
                source, category, currency, select_sql = KIND_SQL[kind]
                cur.execute(select_sql)
                rows = [(code, name or code) for code, name in cur.fetchall()]
                print(f"{kind}: {len(rows)} 只 -> source={source} selectable={selectable}", flush=True)
                if args.apply:
                    cur.executemany(
                        UPSERT_SQL,
                        [(code, source, category, name, selectable, currency) for code, name in rows],
                    )
                total += len(rows)
            if args.apply:
                conn.commit()
    finally:
        conn.close()
    print(f"{'已写入' if args.apply else 'dry-run（加 --apply 才写入）'}: {total} 条配置")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
