# -*- coding: utf-8 -*-
import sys, re, pathlib
sys.stdout.reconfigure(encoding="utf-8")
sys.path.insert(0, str(pathlib.Path(".").resolve()))
env = {}
for line in open(".env", encoding="utf-8"):
    m = re.match(r"^([A-Z0-9_]+)=(.*)$", line.strip())
    if m: env[m.group(1)] = m.group(2).strip().strip('"')
import psycopg
conn = psycopg.connect(host="81.71.158.239", port=5432, user="postgres", password=env.get("PGPASSWORD",""), dbname="bp_mig_test", connect_timeout=15, autocommit=True)
sql = pathlib.Path("ddl/52_index_valuation_domain.sql").read_text(encoding="utf-8")
with conn.cursor() as cur:
    for i in (1,2):
        cur.execute(sql, prepare=False)
        print("52 apply", i, "OK")
    cur.execute("select pg_get_constraintdef(oid) from pg_constraint where conname='ck_index_master_market'")
    print("check:", cur.fetchone()[0])
conn.close()
