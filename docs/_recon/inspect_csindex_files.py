# -*- coding: utf-8 -*-
"""检查中证 OSS 的 perf.xls / closeweight.xls 内容。"""
import io, sys
sys.path.insert(0, "/opt/balanced-portfolio")
sys.stdout.reconfigure(encoding="utf-8")
import pandas as pd
import requests
from bp_ingest.http_session import install_hardened_session

install_hardened_session()
BASE = "https://oss-ch.csindex.com.cn/static/html/csindex/public/uploads/file/autofile"
for name in ("perf", "closeweight", "cons"):
    url = f"{BASE}/{name}/930641{name}.xls"
    r = requests.get(url, timeout=25)
    print(name, "status", r.status_code, "bytes", len(r.content))
    try:
        df = pd.read_excel(io.BytesIO(r.content))
        print("  columns:", list(df.columns)[:12])
        print("  rows:", len(df))
        print(df.head(3).to_string()[:600])
    except Exception as exc:
        print("  parse fail:", type(exc).__name__, str(exc)[:120])
    print()
