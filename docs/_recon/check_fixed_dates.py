import sys
sys.path.insert(0, "/opt/balanced-portfolio")
sys.stdout.reconfigure(encoding="utf-8")
from bp_ingest.config import load_config
from bp_ingest.db import connect
app = load_config()
with connect(app.db) as conn, conn.cursor() as cur:
    for code in ("930743", "930782", "931787CNY00"):
        cur.execute(
            "SELECT trade_date, close, source FROM bp_index_quote_daily "
            "WHERE symbol = %s AND adjust = 'bfq' ORDER BY trade_date DESC LIMIT 4",
            (code,),
        )
        print(code, [(str(r[0]), r[1], r[2]) for r in cur.fetchall()])
    cur.execute("SELECT max(trade_date) FROM bp_index_quote_daily WHERE symbol = '000300' AND adjust='bfq'")
    print("000300 latest:", cur.fetchone()[0])
