"""检查平安是否覆盖中证全指 000985。"""
import sys
sys.path.insert(0, "/opt/balanced-portfolio")
sys.stdout.reconfigure(encoding="utf-8")
from bp_ingest.valuation_pingan import fetch_index_detail
rows = fetch_index_detail(["ZI000985"])
print("rows:", len(rows))
if rows:
    row = rows[0]
    print("code:", row.get("code"), "name:", row.get("indexName"), "pe:", row.get("peRatio"), "pb:", row.get("pbRatio"))