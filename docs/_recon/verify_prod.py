# -*- coding: utf-8 -*-
import sys, re
sys.stdout.reconfigure(encoding="utf-8")
env = {}
for line in open(".env", encoding="utf-8"):
    m = re.match(r"^([A-Z0-9_]+)=(.*)$", line.strip())
    if m: env[m.group(1)] = m.group(2).strip().strip('"')
import psycopg
conn = psycopg.connect(host="81.71.158.239", port=5432, dbname="postgres", user=env.get("PGUSER","postgres"), password=env["PGPASSWORD"], connect_timeout=15)
cur = conn.cursor()
cur.execute("select table_name from information_schema.tables where table_schema='public' and table_name like 'bp_index_%' order by 1")
print("index tables:", [r[0] for r in cur.fetchall()])
cur.execute("select column_name, column_default from information_schema.columns where table_name='bp_index_quote_daily' and column_name='adjust'")
print("quote.adjust:", cur.fetchall())
cur.execute("select count(*) from bp_index_quote_daily where adjust='hfq'")
print("hfq quote rows:", cur.fetchone()[0])
cur.execute("select count(*) from bp_quote_clean where adjust='hfq'")
print("hfq clean rows:", cur.fetchone()[0])
cur.execute("select code from bp_data_source where code in ('pingan_index','csindex_value','binance_futures') order by 1")
print("new sources:", [r[0] for r in cur.fetchall()])
cur.execute("select pg_get_constraintdef(oid) from pg_constraint where conname='pk_bp_index_quote_daily'")
print("quote PK (still old until 53):", cur.fetchone()[0])
conn.close()
