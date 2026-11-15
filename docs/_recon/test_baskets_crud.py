import json, sys, urllib.request
sys.path.insert(0, "/opt/balanced-portfolio")
sys.stdout.reconfigure(encoding="utf-8")
import jwt
from datetime import datetime, timedelta, timezone
from bp_api.settings import load_settings
settings = load_settings()
email = "xingyuliu@outlook.sg"
token = jwt.encode({"sub": email, "role": "admin", "exp": datetime.now(timezone.utc) + timedelta(hours=1)}, settings.jwt_secret, algorithm="HS256")
base = "http://127.0.0.1:8000"
def call(path, method="GET", body=None):
    data = json.dumps(body).encode() if body is not None else None
    req = urllib.request.Request(base + path, data=data, method=method,
                                 headers={"Content-Type": "application/json", "Authorization": "Bearer " + token})
    return json.load(urllib.request.urlopen(req, timeout=60))
assets = [{"symbol": "510300", "source": "etf_em"}, {"symbol": "000905", "source": "cn_index_em"}]
created = call("/api/baskets", "POST", {"name": "JWT 测试篮子", "description": "验证 CRUD", "method": "risk_parity", "assets": assets,
    "params": {"lookback_days": 156, "rebalance_band": 0.05, "risk_free": 0, "start": "2024-01-01"},
    "latest_result": {"annualized_return": 0.0719, "max_drawdown": -0.235, "sharpe": 0.36}})
bid = created["data"]["basket_id"]
print("created:", bid)
print("list rows:", len(call("/api/baskets")["data"]))
copied = call("/api/baskets/" + str(bid) + "/copy", "POST", {"name": "副本"})
cid = copied["data"]["basket_id"]
print("copied:", cid)
call("/api/baskets/" + str(cid), "PATCH", {"name": "改名后"})
detail = call("/api/baskets/" + str(cid))["data"]
print("detail:", detail["name"], "assets:", len(detail["assets"]), "params:", detail["params"])
call("/api/baskets/" + str(cid), "DELETE")
call("/api/baskets/" + str(bid), "DELETE")
print("remaining:", len(call("/api/baskets")["data"]))
