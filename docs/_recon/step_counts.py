# -*- coding: utf-8 -*-
import sys, re
sys.stdout.reconfigure(encoding="utf-8")
env = {}
for line in open(".env", encoding="utf-8"):
    m = re.match(r"^([A-Z0-9_]+)=(.*)$", line.strip())
    if m: env[m.group(1)] = m.group(2).strip().strip('"')
import psycopg
base = dict(host="81.71.158.239", port=5432, user="postgres", password=env.get("PGPASSWORD",""), connect_timeout=15)
with psycopg.connect(**base, dbname="postgres", autocommit=True) as conn:
    with conn.cursor() as cur:
        for t in ["bp_index_quote_daily", "bp_quote_clean", "bp_portfolio_asset", "bp_index_config"]:
            cur.execute(f"select count(*) from {t}")
            print(t, cur.fetchone()[0])
        cur.execute("select count(*) from pg_database where datname='bp_mig_test'")
        if cur.fetchone()[0]:
            cur.execute("drop database bp_mig_test")
        cur.execute("create database bp_mig_test")
        print("scratch db ready")
