import hashlib, json, sys, urllib.request
sys.path.insert(0, "/opt/balanced-portfolio")
sys.stdout.reconfigure(encoding="utf-8")
import jwt
from datetime import datetime, timedelta, timezone
from bp_api.settings import load_settings
settings = load_settings()
print("secret len:", len(settings.jwt_secret), "sha:", hashlib.sha256(settings.jwt_secret.encode()).hexdigest()[:16])
pm2 = open("/tmp/pm2_secret.txt", encoding="utf-8").read().strip()
print("pm2 equal:", pm2 == settings.jwt_secret)
email = "xingyuliu@outlook.sg"
token = jwt.encode({"sub": email, "role": "admin", "exp": datetime.now(timezone.utc) + timedelta(hours=1)}, settings.jwt_secret, algorithm="HS256")
req = urllib.request.Request("http://127.0.0.1:8000/api/baskets", headers={"Authorization": "Bearer " + token})
try:
    print("list:", json.load(urllib.request.urlopen(req, timeout=30)))
except Exception as exc:
    print("FAIL", type(exc).__name__, getattr(exc, "code", ""), str(getattr(exc, "read", lambda: b"")())[:300])
