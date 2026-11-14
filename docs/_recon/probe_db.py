# -*- coding: utf-8 -*-
import sys, os, re
sys.stdout.reconfigure(encoding="utf-8")
env = {}
for line in open(".env", encoding="utf-8"):
    m = re.match(r"^([A-Z0-9_]+)=(.*)$", line.strip())
    if m: env[m.group(1)] = m.group(2).strip().strip('"')
import psycopg
pw = env.get("PGPASSWORD", "")
dsn = f"host={env.get('PGHOST')} port={env.get('PGPORT','5432')} dbname={env.get('PGDATABASE','postgres')} user={env.get('PGUSER','postgres')} password={pw} connect_timeout=15"
try:
    with psycopg.connect(dsn) as conn:
        with conn.cursor() as cur:
            cur.execute("select version(), current_database(), inet_server_addr()::text, inet_server_port(), now()")
            v, db, addr, port, now = cur.fetchone()
            print("[OK] connected")
            print("  server:", v.split(",")[0])
            print("  db:", db, "| addr:", addr, "| port:", port, "| now:", now)
            cur.execute("select count(*) from information_schema.tables where table_schema='public'")
            print("  public tables:", cur.fetchone()[0])
except Exception as e:
    print("[FAIL]", type(e).__name__, str(e)[:200])
