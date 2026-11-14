# -*- coding: utf-8 -*-
import sys, re, time, pathlib
sys.stdout.reconfigure(encoding="utf-8")
env = {}
for line in open(".env", encoding="utf-8"):
    m = re.match(r"^([A-Z0-9_]+)=(.*)$", line.strip())
    if m: env[m.group(1)] = m.group(2).strip().strip('"')
import psycopg
pw = env.get("PGPASSWORD","")
def connect(db):
    return psycopg.connect(host="81.71.158.239", port=5432, user="postgres", password=pw, dbname=db, connect_timeout=15, autocommit=True)

t0 = time.time()
with connect("bp_mig_test") as conn:
    with conn.cursor() as cur:
        schema = pathlib.Path("ddl/schema.sql").read_text(encoding="utf-8")
        try:
            cur.execute(schema, prepare=False)
            print("schema.sql OK", round(time.time()-t0,1), "s")
        except Exception as e:
            print("schema.sql FAIL", type(e).__name__, str(e)[:300])
            raise SystemExit(1)
        cur.execute("select count(*) from information_schema.tables where table_schema='public'")
        print("tables:", cur.fetchone()[0])
        cur.execute("select count(*) from bp_index_config")
        print("config seeds:", cur.fetchone()[0])
        cur.execute("select count(*) from bp_data_source")
        print("sources:", cur.fetchone()[0])
