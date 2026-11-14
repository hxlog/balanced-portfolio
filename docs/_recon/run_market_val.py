# -*- coding: utf-8 -*-
import sys
sys.stdout.reconfigure(encoding="utf-8")
sys.path.insert(0, "/opt/balanced-portfolio")
from bp_ingest.config import load_config, setup_logging
from bp_ingest.db import connect
from bp_ingest.market_valuation import compute

setup_logging()
app = load_config()
with connect(app.db) as conn:
    result = compute(conn)
print(result)
