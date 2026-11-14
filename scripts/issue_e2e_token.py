# -*- coding: utf-8 -*-
"""签发一个验收用 token（明文只打印一次）。"""
import sys
sys.path.insert(0, "/opt/balanced-portfolio")
sys.stdout.reconfigure(encoding="utf-8")
from bp_ingest.config import load_config
from bp_ingest.db import connect
from bp_api.api_tokens import create_token

app = load_config()
with connect(app.db) as conn:
    conn.autocommit = False
    token_id, plain = create_token(conn, "e2e-acceptance", ["quotes", "valuation", "percentile"], None, None)
    conn.commit()
print("TOKEN=" + plain, flush=True)
