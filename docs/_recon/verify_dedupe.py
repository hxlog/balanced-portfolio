# -*- coding: utf-8 -*-
import sys, json, urllib.request, collections
sys.path.insert(0, "/opt/balanced-portfolio")
sys.stdout.reconfigure(encoding="utf-8")
from bp_ingest.config import load_config
from bp_ingest.db import connect
from bp_api.api_tokens import create_token

app = load_config()
with connect(app.db) as conn:
    conn.autocommit = False
    _, token = create_token(conn, "dedupe-check", ["quotes"], None, None)
    conn.commit()

url = "http://127.0.0.1:8000/api/v1/market/daily?codes=000300&start=2026-10-01&end=2026-11-14"
req = urllib.request.Request(url, headers={"Authorization": "Bearer " + token})
body = json.load(urllib.request.urlopen(req, timeout=30))
rows = body["data"]
pairs = collections.Counter((r["code"], r["date"]) for r in rows)
dups = {k: v for k, v in pairs.items() if v > 1}
print("rows:", len(rows), "unique dates:", len(pairs), "duplicates:", len(dups))
print("meta:", {k: body["meta"].get(k) for k in ("rows", "collapse", "source")})
