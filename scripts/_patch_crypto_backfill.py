# -*- coding: utf-8 -*-
path = "scripts/crypto_extra_backfill.py"
s = open(path, encoding="utf-8").read()
s = s.replace('sys.path.insert(0, "/opt/balanced-portfolio")\nsys.path.insert(0, "/opt/balanced-portfolio/bp_ingest")\n', 'sys.path.insert(0, "/opt/balanced-portfolio")\n')
s = s.replace('from bp_ingest.config import load_config', 'from bp_ingest.config import load_config')
s = s.replace("def fetch_funding(conn, codes: list[str], days: int) -> int:", "def fetch_funding(app, codes: list[str], days: int) -> int:")
s = s.replace("with connect(conn.info if False else load_config().db) as c2, c2.cursor() as cur:", "with connect(app.db) as c2, c2.cursor() as cur:")
s = s.replace("def fetch_top_ratio(conn, codes: list[str], days: int, period: str = \"1h\") -> int:", "def fetch_top_ratio(app, codes: list[str], days: int, period: str = \"1h\") -> int:")
s = s.replace("with connect(load_config().db) as c2, c2.cursor() as cur:", "with connect(app.db) as c2, c2.cursor() as cur:")
s = s.replace("funding = fetch_funding(None, codes, args.days)", "funding = fetch_funding(cfg, codes, args.days)")
s = s.replace("ratios = fetch_top_ratio(None, codes, args.days)", "ratios = fetch_top_ratio(cfg, codes, args.days)")
open(path, "w", encoding="utf-8").write(s)
print("patched backfill")
