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
cur.execute("select column_name from information_schema.columns where table_name = %s order by ordinal_position", ("bp_data_source",))
print("bp_data_source:", [r[0] for r in cur.fetchall()])
cur.execute("select column_name from information_schema.columns where table_name = %s order by ordinal_position", ("bp_index_config",))
print("bp_index_config:", [r[0] for r in cur.fetchall()])
conn.close()
