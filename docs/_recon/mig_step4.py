# -*- coding: utf-8 -*-
import sys, re
sys.stdout.reconfigure(encoding="utf-8")
env = {}
for line in open(".env", encoding="utf-8"):
    m = re.match(r"^([A-Z0-9_]+)=(.*)$", line.strip())
    if m: env[m.group(1)] = m.group(2).strip().strip('"')
import psycopg
pw = env.get("PGPASSWORD","")
conn = psycopg.connect(host="81.71.158.239", port=5432, user="postgres", password=pw, dbname="bp_mig_test", connect_timeout=15, autocommit=True)
with conn.cursor() as cur:
    cur.execute("delete from bp_index_valuation_daily")
    cur.execute("""insert into bp_index_valuation_daily (index_code, trade_date, calc_src, pe_ttm, is_primary)
                   values ('930641','2026-11-13','pingan_index',23.27,true),
                          ('930641','2026-11-13','csindex_value',19.55,false)""")
    cur.execute("select calc_src, pe_ttm, is_primary from bp_index_valuation_daily order by 1")
    print("multi-source coexist:", cur.fetchall())
    for label, sqlv in [
        ("negative PE", "insert into bp_index_valuation_daily (index_code,trade_date,calc_src,pe_ttm) values ('930641','2026-11-12','pingan_index',-5)"),
        ("bad level", "insert into bp_index_valuation_daily (index_code,trade_date,calc_src,level_pe) values ('930641','2026-11-11','pingan_index','很贵')"),
        ("bad metric", "insert into bp_index_valuation_series (index_code,trade_date,metric,calc_src,value) values ('930641','2026-11-13','roe_ttm','pingan_index',1)"),
        ("bad window", "insert into bp_index_percentile (index_code,as_of_date,metric,window_key,calc_src,sample_size) values ('930641','2026-11-13','pe_ttm','3y','pingan_index',10)"),
        ("bad source fk", "insert into bp_index_valuation_daily (index_code,trade_date,calc_src) values ('930641','2026-11-10','not_a_source')"),
    ]:
        try:
            cur.execute(sqlv)
            print(f"{label}: FAIL (allowed)")
        except Exception as e:
            print(f"{label}: OK ({getattr(e,'sqlstate','')})")
    cur.execute("delete from bp_index_valuation_daily where not is_primary")
    cur.execute("select count(*) from bp_index_valuation_daily")
    print("cleanup rows:", cur.fetchone()[0])
    # 触发器存在性
    cur.execute("select tgname from pg_trigger where tgrelid='bp_index_master'::regclass and not tgisinternal")
    print("triggers:", [r[0] for r in cur.fetchall()])
    # 配置表 FK
    cur.execute("select conname, pg_get_constraintdef(oid) from pg_constraint where conname='fk_bp_index_config_index_code'")
    print("config fk:", cur.fetchall())
conn.close()
print("DONE")
