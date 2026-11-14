# -*- coding: utf-8 -*-
import re, sys, psycopg
sys.stdout.reconfigure(encoding="utf-8")
env = {}
for line in open(".env", encoding="utf-8"):
    m = re.match(r"^([A-Z0-9_]+)=(.*)$", line.strip())
    if m:
        env[m.group(1)] = m.group(2).strip().strip('"')
conn = psycopg.connect(host="81.71.158.239", dbname="postgres", user="postgres", password=env["PGPASSWORD"], connect_timeout=15)
cur = conn.cursor()
cur.execute("select count(*), max(captured_at) from bp_crypto_futures_snapshot_5m")
print("snapshots:", cur.fetchone())
conn.close()
