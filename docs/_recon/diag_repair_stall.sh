#!/usr/bin/env bash
cd /opt/balanced-portfolio
echo "=== 进程 ==="
pgrep -af repair_stale_quotes | head -2 || echo done
echo "=== 日志尾 ==="
tail -c 600 /tmp/repair_quotes3.log | tr -d "\r" | tail -6
echo "=== CS relay 计时（session 复用） ==="
timeout 90 .venv/bin/python - <<'PY'
import time, requests
s = requests.Session()
s.proxies = {"http": "http://127.0.0.1:10809", "https": "http://127.0.0.1:10809"}
s.headers.update({"User-Agent": "Mozilla/5.0 Chrome/120", "Referer": "https://www.csindex.com.cn/"})
for code in ("000905", "930782"):
    t0 = time.time()
    try:
        r = s.get("https://www.csindex.com.cn/csindex-home/perf/index-perf",
                  params={"indexCode": code, "startDate": "20261001", "endDate": "20261115"}, timeout=25)
        rows = (r.json().get("data") or []) if r.status_code == 200 else []
        print(code, r.status_code, "rows", len(rows), "last", rows[-1].get("tradeDate") if rows else None, "%.1fs" % (time.time()-t0))
    except Exception as exc:
        print(code, "FAIL", type(exc).__name__, str(exc)[:80], "%.1fs" % (time.time()-t0))
PY
