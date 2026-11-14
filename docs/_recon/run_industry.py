# -*- coding: utf-8 -*-
import sys
sys.path.insert(0, "/opt/balanced-portfolio")
sys.stdout.reconfigure(encoding="utf-8")
from bp_ingest.config import load_config, setup_logging
from bp_ingest.db import connect
from bp_ingest.stock_industry import sync_industries

setup_logging()
app = load_config()
with connect(app.db) as conn:
    print(sync_industries(conn))
