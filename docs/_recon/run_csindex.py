# -*- coding: utf-8 -*-
import sys
sys.path.insert(0, "/opt/balanced-portfolio")
sys.stdout.reconfigure(encoding="utf-8")
from bp_ingest.config import load_config, setup_logging
from bp_ingest.db import connect
from bp_ingest.csindex_value import run

setup_logging()
app = load_config()
with connect(app.db) as conn:
    conn.autocommit = False
    result = run(conn, limit=None)
print(result)
