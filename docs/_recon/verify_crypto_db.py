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
for table in ("bp_crypto_contract", "bp_crypto_futures_snapshot_5m", "bp_crypto_futures_percentile"):
    cur.execute(f"select count(*) from {table}")
    print(table, cur.fetchone()[0])
cur.execute("""
    select contract_code, mark_price, oi_notional, long_short_ratio, taker_buy_sell_ratio, basis_pct
    from bp_crypto_futures_snapshot_5m order by oi_notional desc nulls last limit 3
""")
for row in cur.fetchall():
    print("top:", [round(v, 4) if isinstance(v, float) else v for v in row])
cur.execute("select metric, count(*), round(avg(pct)::numeric,1) from bp_crypto_futures_percentile group by metric")
print(cur.fetchall())
conn.close()
