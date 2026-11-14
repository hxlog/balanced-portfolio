# -*- coding: utf-8 -*-
import sys, re, pathlib
sys.stdout.reconfigure(encoding="utf-8")
env = {}
for line in open(".env", encoding="utf-8"):
    m = re.match(r"^([A-Z0-9_]+)=(.*)$", line.strip())
    if m: env[m.group(1)] = m.group(2).strip().strip('"')
import psycopg
pw = env.get("PGPASSWORD","")
conn = psycopg.connect(host="81.71.158.239", port=5432, user="postgres", password=pw, dbname="bp_mig_test", connect_timeout=15, autocommit=True)
mig = pathlib.Path("ddl/52_index_valuation_domain.sql").read_text(encoding="utf-8")
with conn.cursor() as cur:
    for i in (1,2,3):
        try:
            cur.execute(mig, prepare=False)
            print(f"apply#{i}: OK")
        except Exception as e:
            print(f"apply#{i}: FAIL", type(e).__name__, str(e)[:400]); raise SystemExit(1)
    cur.execute("select table_name from information_schema.tables where table_schema='public' and table_name like 'bp_index_%' order by 1")
    print("tables:", [r[0] for r in cur.fetchall()])
    cur.execute("select code from bp_data_source where code in ('pingan_index','csindex_value','binance_futures') order by 1")
    print("sources:", [r[0] for r in cur.fetchall()])
    # 约束有效性：主口径唯一索引
    cur.execute("insert into bp_index_master (index_code, market, name) values ('930641','CSI','中证中药')")
    cur.execute("""insert into bp_index_valuation_daily (index_code, trade_date, calc_src, pe_ttm, is_primary)
                   values ('930641','2026-11-13','pingan_index',23.27,true)""")
    try:
        cur.execute("""insert into bp_index_valuation_daily (index_code, trade_date, calc_src, pe_ttm, is_primary)
                       values ('930641','2026-11-13','csindex_value',19.55,true)""")
        print("primary uniqueness: FAIL (allowed 2 primaries)")
    except Exception as e:
        print("primary uniqueness: OK (rejected) ->", getattr(e, 'sqlstate', ''))
    conn.rollback()
    cur.execute("select count(*) from bp_index_valuation_daily")
    print("rows after rollback:", cur.fetchone()[0])
    # 非主口径可并存
    cur.execute("""insert into bp_index_valuation_daily (index_code, trade_date, calc_src, pe_ttm, is_primary)
                   values ('930641','2026-11-13','pingan_index',23.27,true),
                          ('930641','2026-11-13','csindex_value',19.55,false)""")
    cur.execute("select calc_src, pe_ttm, is_primary from bp_index_valuation_daily order by 1")
    print("multi-source:", cur.fetchall())
    # 负 PE 应被拒
    try:
        cur.execute("""insert into bp_index_valuation_daily (index_code, trade_date, calc_src, pe_ttm) values ('930641','2026-11-12','pingan_index',-5)""")
        print("negative PE check: FAIL")
    except Exception as e:
        print("negative PE check: OK ->", getattr(e, 'sqlstate', ''))
conn.close()
print("DONE")
