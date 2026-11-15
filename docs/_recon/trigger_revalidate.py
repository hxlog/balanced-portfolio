"""触发 Next 估值缓存失效（读 .env 里的内部 token）。"""
import json, sys, urllib.request
token = ""
for line in open("/opt/balanced-portfolio/.env", encoding="utf-8"):
    if line.startswith("BP_INTERNAL_REVALIDATE_TOKEN="):
        token = line.split("=", 1)[1].strip().strip("'\"")
        break
req = urllib.request.Request(
    "http://127.0.0.1:3000/api/revalidate/valuation",
    data=json.dumps({"tags": ["valuation"]}).encode(),
    headers={"Content-Type": "application/json", "X-Internal-Token": token},
    method="POST",
)
try:
    with urllib.request.urlopen(req, timeout=20) as resp:
        print("revalidate:", resp.status, resp.read().decode()[:200])
except Exception as exc:
    print("revalidate failed:", type(exc).__name__, exc)