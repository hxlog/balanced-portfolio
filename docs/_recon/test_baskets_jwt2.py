import json, sys, urllib.request
sys.path.insert(0, "/opt/balanced-portfolio")
sys.stdout.reconfigure(encoding="utf-8")
import jwt
from datetime import datetime, timedelta, timezone
env = {}
for line in open("/opt/balanced-portfolio/.env", encoding="utf-8"):
    line = line.strip()
    if not line or line.startswith("#") or "=" not in line: continue
    k, v = line.split("=", 1); env[k.strip()] = v.strip()
secret = env.get("BP_JWT_SECRET", "").strip().strip('"').strip("'")
print("secret len:", len(secret))
from bp_ingest.config import load_config
from bp_ingest.db import connect
app = load_config()
with connect(app.db) as conn, conn.cursor() as cur:
    cur.execute("SELECT email FROM bp_user WHERE role='admin' LIMIT 1")
    email = cur.fetchone()[0]
token = jwt.encode({"sub": email, "role": "admin", "exp": datetime.now(timezone.utc) + timedelta(hours=1)}, secret, algorithm="HS256")
base = "http://127.0.0.1:8000"
def call(path, method="GET", body=None):
    data = json.dumps(body).encode() if body is not None else None
    req = urllib.request.Request(base + path, data=data, method=method,
                                 headers={"Content-Type": "application/json", "Authorization": "Bearer " + token})
    return json.load(urllib.request.urlopen(req, timeout=60))
assets = [{"symbol": "510300", "source": "etf_em"}, {"symbol": "000905", "source": "cn_index_em"}]
created = call("/api/baskets", "POST", {"name": "JWT 测试篮子", "method": "risk_parity", "assets": assets,
    "params": {"lookback_days": 156, "rebalance_band": 0.05, "risk_free": 0, "start": "2024-01-01"},
    "latest_result": {"annualized_return": 0.0719, "max_drawdown": -0.235, "sharpe": 0.36}})
bid = created["data"]["basket_id"]
print("created:", bid)
rows = call("/api/baskets")["data"]
print("list rows:", len(rows))
copied = call("/api/baskets/" + str(bid) + "/copy", "POST", {"name": "副本"})
cid = copied["data"]["basket_id"]
print("copied:", cid)
call("/api/baskets/" + str(cid), "PATCH", {"name": "改名后"})
detail = call("/api/baskets/" + str(cid))["data"]
print("detail:", detail["name"], "assets:", len(detail["assets"]))
call("/api/baskets/" + str(cid), "DELETE")
call("/api/baskets/" + str(bid), "DELETE")
print("remaining:", len(call("/api/baskets")["data"]))
