# -*- coding: utf-8 -*-
p = "scripts/local_backfill_stocks.py"
s = open(p, encoding="utf-8").read()
s = s.replace("from bp_ingest.db import connect  # noqa: E402", "import psycopg  # noqa: E402")
s = s.replace('''def db_conn():
    env = load_env()
    host = os.getenv("BP_BACKFILL_DB_HOST") or "81.71.158.239"
    return connect({
        "host": host,
        "port": int(env.get("PGPORT", "5432")),
        "dbname": env.get("PGDATABASE", "postgres"),
        "user": env.get("PGUSER", "postgres"),
        "password": env.get("PGPASSWORD", ""),
    })''',
'''def db_conn():
    env = load_env()
    host = os.getenv("BP_BACKFILL_DB_HOST") or "81.71.158.239"
    conninfo = (
        "host=" + host
        + " port=" + str(env.get("PGPORT", "5432"))
        + " dbname=" + env.get("PGDATABASE", "postgres")
        + " user=" + env.get("PGUSER", "postgres")
        + " password=" + env.get("PGPASSWORD", "")
    )
    return psycopg.connect(conninfo)''')
open(p, "w", encoding="utf-8").write(s)
print("patched conn")
