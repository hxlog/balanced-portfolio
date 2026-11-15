# -*- coding: utf-8 -*-
import re

def patch(path, marker):
    s = open(path, encoding="utf-8").read()
    if "psycopg.connect(**" in s:
        print(path, "already patched"); return
    # 统一改为 kwargs 连接（PGPASSWORD 含 # 等特殊字符时 conninfo 会解析失败）
    s = re.sub(
        r'conn = psycopg\.connect\(\s*"host=" \+ host[\s\S]*?" password=" \+ env\.get\("PGPASSWORD", ""\)\s*\)',
        'conn = psycopg.connect(host=host, port=int(env.get("PGPORT", "5432")),\n'
        '        dbname=env.get("PGDATABASE", "postgres"), user=env.get("PGUSER", "postgres"),\n'
        '        password=env.get("PGPASSWORD", ""))',
        s,
    )
    s = re.sub(
        r'conn = psycopg\.connect\(\s*"host=" \+ \(os\.getenv\("BP_ETL_DB_HOST"\) or "127\.0\.0\.1"\)[\s\S]*?" password=" \+ env\.get\("PGPASSWORD", ""\)\s*\)',
        'conn = psycopg.connect(host=(os.getenv("BP_ETL_DB_HOST") or "127.0.0.1"),\n'
        '        port=int(env.get("PGPORT", "5432")), dbname=env.get("PGDATABASE", "postgres"),\n'
        '        user=env.get("PGUSER", "postgres"), password=env.get("PGPASSWORD", ""))',
        s,
    )
    open(path, "w", encoding="utf-8").write(s)
    print(path, "patched:", "psycopg.connect(**" not in s and "password=env.get" in s)

patch("scripts/incremental_stock_quotes.py", "stock")
patch("scripts/incremental_fund_nav.py", "fund")
patch("scripts/asset_coverage_report.py", "report")
