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
cur.execute("select distinct market from bp_trading_calendar")
print("markets:", [r[0] for r in cur.fetchall()])
cur.execute("select max(cal_date) from bp_trading_calendar where is_trading and cal_date <= current_date")
print("last trading day <= today:", cur.fetchone()[0])
conn.close()
