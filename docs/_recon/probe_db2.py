# -*- coding: utf-8 -*-
import sys, re
sys.stdout.reconfigure(encoding="utf-8")
env = {}
for line in open(".env", encoding="utf-8"):
    m = re.match(r"^([A-Z0-9_]+)=(.*)$", line.strip())
    if m: env[m.group(1)] = m.group(2).strip().strip('"')
import psycopg
for host in ["81.71.158.239", "100.75.138.35"]:
    dsn = f"host={host} port=5432 dbname=postgres user=postgres password={env.get('PGPASSWORD','')} connect_timeout=8"
    try:
        with psycopg.connect(dsn) as conn:
            with conn.cursor() as cur:
                cur.execute("select inet_server_addr()::text, current_database(), (select count(*) from information_schema.tables where table_schema='public')")
                print(f"[OK] {host} ->", cur.fetchone())
    except Exception as e:
        print(f"[FAIL] {host}:", type(e).__name__, str(e)[:120])
