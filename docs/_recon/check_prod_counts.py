# -*- coding: utf-8 -*-
import sys, re
sys.stdout.reconfigure(encoding="utf-8")
env = {}
for line in open(".env", encoding="utf-8"):
    m = re.match(r"^([A-Z0-9_]+)=(.*)$", line.strip())
    if m: env[m.group(1)] = m.group(2).strip().strip('"')
import psycopg
conn = psycopg.connect(host="81.71.158.239", port=5432, dbname="postgres", user="postgres", password=env["PGPASSWORD"], connect_timeout=15)
cur = conn.cursor()
for t in ["bp_index_master","bp_index_valuation_daily","bp_index_valuation_series","bp_index_percentile"]:
    cur.execute(f"select count(*) from {t}")
    print(t, cur.fetchone()[0])
conn.close()
