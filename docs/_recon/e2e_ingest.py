# -*- coding: utf-8 -*-
import sys, re, time, json, pathlib
sys.stdout.reconfigure(encoding="utf-8")
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[2]))
env = {}
for line in open(".env", encoding="utf-8"):
    m = re.match(r"^([A-Z0-9_]+)=(.*)$", line.strip())
    if m: env[m.group(1)] = m.group(2).strip().strip('"')
import psycopg

t0 = time.time()
conn = psycopg.connect(host="81.71.158.239", port=5432, user="postgres",
                       password=env.get("PGPASSWORD",""), dbname="bp_mig_test",
                       connect_timeout=15, autocommit=False)
with conn.cursor() as cur:
    cur.execute("truncate bp_index_valuation_daily, bp_index_valuation_series, bp_index_percentile, bp_index_master cascade")
conn.commit()
print("tables truncated", round(time.time()-t0,1))

from bp_ingest.valuation_ingest import run_valuation_ingest
try:
    summary = run_valuation_ingest(conn)
    conn.commit()
    print("SUMMARY:", json.dumps({k: v for k, v in summary.items() if k != "errors"}, ensure_ascii=False, default=str))
    print("errors:", len(summary.get("errors") or []), (summary.get("errors") or [])[:3])
except Exception as e:
    conn.rollback()
    print("INGEST FAIL:", type(e).__name__, str(e)[:400])
    raise SystemExit(1)

with conn.cursor() as cur:
    for t in ["bp_index_master","bp_index_valuation_daily","bp_index_valuation_series","bp_index_percentile"]:
        cur.execute(f"select count(*) from {t}")
        print(t, cur.fetchone()[0])
    cur.execute("select index_code, name, market, index_type from bp_index_master order by index_code limit 5")
    print("master sample:", cur.fetchall())
    cur.execute("select index_code, trade_date, pe_ttm, pb, dividend_yield_ttm, erp, is_primary from bp_index_valuation_daily order by trade_date desc, index_code limit 3")
    print("daily sample:", cur.fetchall())
    cur.execute("select index_code, metric, window_key, pct, mean, sample_size from bp_index_percentile where index_code='930641' order by metric, window_key")
    print("930641 percentiles:", cur.fetchall()[:12])
conn.close()
print("DONE in", round(time.time()-t0,1), "s")
