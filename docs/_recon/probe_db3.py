# -*- coding: utf-8 -*-
import sys, re
sys.stdout.reconfigure(encoding="utf-8")
env = {}
for line in open(".env", encoding="utf-8"):
    m = re.match(r"^([A-Z0-9_]+)=(.*)$", line.strip())
    if m: env[m.group(1)] = m.group(2).strip().strip('"')
import psycopg
base = dict(host="81.71.158.239", port=5432, user="postgres", password=env.get("PGPASSWORD",""), dbname="postgres")
with psycopg.connect(**base, autocommit=True, connect_timeout=10) as conn:
    with conn.cursor() as cur:
        cur.execute("select current_user, usesuper from pg_user where usename=current_user")
        print("user:", cur.fetchone())
        cur.execute("select extname, extversion from pg_extension")
        print("extensions:", cur.fetchall())
        cur.execute("select datname from pg_database order by 1")
        print("dbs:", [r[0] for r in cur.fetchall()])
        # multi-statement support test
        try:
            cur.execute("select 1; select 2;", prepare=False)
            print("multi-stmt: OK")
        except Exception as e:
            print("multi-stmt: FAIL", type(e).__name__, str(e)[:120])
