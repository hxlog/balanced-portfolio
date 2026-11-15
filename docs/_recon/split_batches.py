# -*- coding: utf-8 -*-
"""把未回填的 symbol 拆成 4 批，写 /tmp/vbatch_{i}.txt。"""
import re, sys
sys.stdout.reconfigure(encoding="utf-8")
import psycopg
env = {}
for line in open(".env", encoding="utf-8"):
    m = re.match(r"^([A-Z0-9_]+)=(.*)$", line.strip())
    if m:
        env[m.group(1)] = m.group(2).strip().strip('"')
conn = psycopg.connect(host="81.71.158.239", dbname="postgres", user="postgres", password=env["PGPASSWORD"], connect_timeout=15)
cur = conn.cursor()
cur.execute("select symbol from bp_index_config where is_deleted = 0 and category = 'index' and index_code is not null")
all_syms = sorted({row[0] for row in cur.fetchall()})
cur.execute("select distinct symbol from bp_index_quote_daily where adjust = 'bfq'")
have = {row[0] for row in cur.fetchall()}
missing = [s for s in all_syms if s not in have]
print("all:", len(all_syms), "have:", len(have), "missing:", len(missing))
for i in range(4):
    chunk = missing[i::4]
    with open(f"/tmp/vbatch_{i}.txt", "w", encoding="utf-8") as f:
        f.write("\n".join(chunk))
    print(f"batch{i}: {len(chunk)}")
conn.close()
