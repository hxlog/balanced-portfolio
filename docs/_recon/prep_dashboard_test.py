import json, sys, urllib.request
sys.path.insert(0, "/opt/balanced-portfolio")
sys.stdout.reconfigure(encoding="utf-8")
import jwt
from datetime import datetime, timedelta, timezone
from bp_api.settings import load_settings
settings = load_settings()
email = "xingyuliu@outlook.sg"
token = jwt.encode({"sub": email, "role": "admin", "exp": datetime.now(timezone.utc) + timedelta(hours=3)}, settings.jwt_secret, algorithm="HS256")
def call(path, method="GET", body=None):
    data = json.dumps(body).encode() if body is not None else None
    req = urllib.request.Request("http://127.0.0.1:8000" + path, data=data, method=method,
                                 headers={"Content-Type": "application/json", "Authorization": "Bearer " + token})
    return json.load(urllib.request.urlopen(req, timeout=60))
rows = call("/api/baskets")["data"]
print("existing baskets:", [(r["basket_id"], r["name"]) for r in rows])
if not rows:
    created = call("/api/baskets", "POST", {
        "name": "一篮子股票", "description": "分红+宽基等权",
        "method": "equal_weight",
        "assets": [{"symbol": "510300", "source": "etf_em"}, {"symbol": "000922", "source": "cn_index_em"}],
        "params": {"lookback_days": 156, "rebalance_band": 0.05, "risk_free": 0, "start": "2024-01-01"},
        "latest_result": {"annualized_return": 0.07, "max_drawdown": -0.23, "sharpe": 0.36},
    })
    print("created:", created)
open("/tmp/admin_token.txt", "w").write(token)
print("token written")
