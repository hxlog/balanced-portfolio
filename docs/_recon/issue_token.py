# -*- coding: utf-8 -*-
"""在服务器上签发一个测试用对外 API token（明文只打印一次）。"""
import sys
sys.path.insert(0, "/opt/balanced-portfolio")
sys.stdout.reconfigure(encoding="utf-8")
from bp_ingest.config import load_config
from bp_ingest.db import connect
from bp_api.api_tokens import create_token

app = load_config()
with connect(app.db) as conn:
    conn.autocommit = False
    token_id, plain = create_token(conn, "smoke-test", ["quotes", "valuation", "percentile"], None, None)
    conn.commit()
print(token_id)
print(plain)
