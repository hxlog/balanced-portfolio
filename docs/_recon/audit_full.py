# -*- coding: utf-8 -*-
"""全量数据完整性/有效性/时效性审计（生产库）。"""
import re, sys, statistics
sys.stdout.reconfigure(encoding="utf-8")
import psycopg
env = {}
for line in open(".env", encoding="utf-8"):
    m = re.match(r"^([A-Z0-9_]+)=(.*)$", line.strip())
    if m:
        env[m.group(1)] = m.group(2).strip().strip('"')
conn = psycopg.connect(host="81.71.158.239", dbname="postgres", user="postgres", password=env["PGPASSWORD"], connect_timeout=15)
cur = conn.cursor()
cur.execute("select count(*) from bp_index_master")
total = cur.fetchone()[0]
cur.execute("select count(*) from bp_index_master where is_tracked")
tracked = cur.fetchone()[0]
print("master:", total, "tracked:", tracked)
cur.execute("""
  select count(*),
         count(pe_ttm), count(pb), count(dividend_yield_ttm), count(erp),
         min(trade_date), max(trade_date)
  from bp_index_valuation_daily where is_primary
""")
print("daily rows/nonnull/max:", cur.fetchone())
cur.execute("""
  select count(distinct index_code) from bp_index_valuation_daily
  where trade_date = (select max(trade_date) from bp_index_valuation_daily)
""")
print("latest-date distinct indices:", cur.fetchone()[0])
print("--- 有效性检查 ---")
cur.execute("select count(*) from bp_index_valuation_daily where pe_ttm is not null and (pe_ttm <= 0 or pe_ttm > 1000)")
print("bad pe:", cur.fetchone()[0])
cur.execute("select count(*) from bp_index_valuation_daily where pb is not null and (pb <= 0 or pb > 100)")
print("bad pb:", cur.fetchone()[0])
cur.execute("select count(*) from bp_index_percentile where pct < 0 or pct > 100")
print("bad pct:", cur.fetchone()[0])
cur.execute("select count(*), count(distinct metric), count(distinct window_key) from bp_index_percentile")
print("percentile rows/metrics/windows:", cur.fetchone())
cur.execute("""
  select count(distinct index_code) from bp_index_percentile
  where metric = chr(112)||chr(101)||chr(95)||chr(116)||chr(116)||chr(109)
""")
print("indices with PE percentile:", cur.fetchone()[0])
print("--- 全市场估值 ---")
cur.execute("select board, trade_date, pe_median, pb_median, sample_size, pct_pe from bp_market_valuation_daily order by trade_date desc, board limit 6")
for row in cur.fetchall(): print("  ", row)
print("--- 行情覆盖（指数）---")
cur.execute("""
  select count(distinct symbol) from bp_quote_clean
  where adjust = chr(98)||chr(102)||chr(113)
""")
print("clean symbols bfq:", cur.fetchone()[0])
conn.close()
