# -*- coding: utf-8 -*-
"""小样本端到端：验证 13 个此前缺失市场映射的指数现在可正确入库。"""
import sys, re, pathlib, json, time
sys.stdout.reconfigure(encoding="utf-8")
sys.path.insert(0, str(pathlib.Path(".").resolve()))
env = {}
for line in open(".env", encoding="utf-8"):
    m = re.match(r"^([A-Z0-9_]+)=(.*)$", line.strip())
    if m: env[m.group(1)] = m.group(2).strip().strip('"')
import psycopg
from bp_ingest.valuation_pingan import (
    fetch_index_universe, fetch_index_detail, fetch_index_description,
    fetch_bond10_history, normalize_index_row,
)

targets = {"FI888888","INESC","SGEMASIAUP","SGESHAU","CZC000201","CICSPSADRP","XI830009",
           "FIWISAUNT","FIGPCCH003","FIGPCSP006","SGASIATECP","SGEAU9999","DCEDCESMFI",
           "930641","000300","000905"}
print("fetching universe...", flush=True)
universe = fetch_index_universe()
print("universe rows:", len(universe), flush=True)
codes = [r.get("code") for r in universe]
wanted = [c for c in codes if c in targets or (c and c.startswith(("ZI930641","SH000300","SH000905")))]
print("wanted:", wanted, flush=True)
print("fetching detail for", len(wanted), "codes...", flush=True)
detail = fetch_index_detail(wanted)
print("detail rows:", len(detail), flush=True)
norm = [normalize_index_row(r) for r in detail]
bad = [n for n in norm if not n.get("market")]
print("normalized:", len(norm), "| missing market:", len(bad), flush=True)
for n in norm[:20]:
    print(" ", n.get("index_code"), n.get("market"), n.get("name"), n.get("pe_ttm"), flush=True)
