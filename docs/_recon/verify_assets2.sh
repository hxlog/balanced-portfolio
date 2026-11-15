#!/usr/bin/env bash
cd /opt/balanced-portfolio
pm2 restart bp-api >/dev/null
sleep 5
.venv/bin/python - <<'PY'
import json, urllib.request
for path in ("/api/assets/unified?q=600519&limit=5", "/api/assets/unified?type=index&limit=3", "/api/assets/unified?type=fund&q=005827&limit=2", "/api/assets/unified?type=stock&limit=3"):
    try:
        d = json.load(urllib.request.urlopen("http://127.0.0.1:8000" + path, timeout=90))
        rows = d.get("data") or []
        print(path.split("?")[1][:34], "rows:", len(rows), "total:", (d.get("meta") or {}).get("total"))
        for row in rows[:2]:
            print("  ", row["type"], row["code"], row["name"], row["last_date"])
    except Exception as exc:
        print(path, "FAIL", type(exc).__name__, getattr(exc, "code", ""))
PY
