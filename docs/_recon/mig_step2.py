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
mig = pathlib.Path("ddl/51_quote_adjust_dimension.sql").read_text(encoding="utf-8")

with conn.cursor() as cur:
    for i in (1, 2, 3):
        try:
            cur.execute(mig, prepare=False)
            print(f"apply#{i}: OK")
        except Exception as e:
            print(f"apply#{i}: FAIL", type(e).__name__, str(e)[:300]); raise SystemExit(1)

    cur.execute("select column_name, data_type, is_nullable, column_default from information_schema.columns where table_name='bp_index_quote_daily' and column_name in ('adjust','row_hash')")
    print("quote cols:", cur.fetchall())
    cur.execute("select pg_get_constraintdef(oid) from pg_constraint where conname='pk_bp_index_quote_daily'")
    print("quote PK:", cur.fetchone()[0])
    cur.execute("select pg_get_constraintdef(oid) from pg_constraint where conname='pk_bp_quote_clean'")
    print("clean PK:", cur.fetchone()[0])
    cur.execute("select pg_get_expr(adbin, adrelid) from pg_attribute a join pg_attrdef d on d.adrelid=a.attrelid and d.adnum=a.attnum where a.attrelid='bp_index_quote_daily'::regclass and a.attname='row_hash'")
    print("row_hash expr:", cur.fetchone()[0])

    # 三种口径并存测试
    cur.execute("""insert into bp_index_quote_daily (trade_date, symbol, source, close, adjust)
                   values ('2026-11-13','600036','etf_em',1,'bfq'),('2026-11-13','600036','etf_em',2,'qfq'),('2026-11-13','600036','etf_em',3,'hfq')""")
    cur.execute("select symbol, source, adjust, close from bp_index_quote_daily order by adjust")
    print("3 rows coexist:", cur.fetchall())
    cur.execute("select count(distinct row_hash) from bp_index_quote_daily")
    print("distinct row_hash:", cur.fetchone()[0])

    # 重复插入同口径应更新而非新增
    cur.execute("""insert into bp_index_quote_daily (trade_date, symbol, source, close, adjust)
                   values ('2026-11-13','600036','etf_em',9,'hfq')
                   on conflict (symbol, source, adjust, trade_date) do update set close=excluded.close""")
    cur.execute("select count(*), max(close) from bp_index_quote_daily where adjust='hfq'")
    print("upsert hfq:", cur.fetchone())

    # ETF 回填验证：先插 bfq 的 etf 行，再跑回填语句
    cur.execute("delete from bp_index_quote_daily")
    cur.execute("""insert into bp_index_quote_daily (trade_date, symbol, source, close, adjust)
                   values ('2026-11-13','510050','etf_em',1,'bfq')""")
    cur.execute("update bp_index_quote_daily set adjust='hfq' where source in ('etf_em','etf_tx') and adjust='bfq'")
    cur.execute("select adjust from bp_index_quote_daily where symbol='510050'")
    print("etf backfill ->", cur.fetchone()[0])
    cur.execute("select count(*) from bp_index_config where adjust <> 'bfq'")
    print("config non-bfq:", cur.fetchone()[0])
    cur.execute("select count(*) from bp_index_config where array_length(adjust_modes,1) > 1")
    print("config multi-mode:", cur.fetchone()[0])
conn.close()
print("DONE")
