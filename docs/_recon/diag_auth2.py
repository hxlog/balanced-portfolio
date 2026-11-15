import hashlib, json, sys, urllib.request, os
sys.path.insert(0, "/opt/balanced-portfolio")
sys.stdout.reconfigure(encoding="utf-8")
from bp_api.settings import load_settings
from bp_api.auth import create_token, decode_token, get_user_by_email
settings = load_settings()
print("secret len:", len(settings.jwt_secret))
print("sha:", hashlib.sha256(settings.jwt_secret.encode()).hexdigest()[:16])
with open("/tmp/pm2_secret.txt", encoding="utf-8") as fh:
    pm2_secret = fh.read().strip()
print("pm2 len:", len(pm2_secret), "sha:", hashlib.sha256(pm2_secret.encode()).hexdigest()[:16], "equal:", pm2_secret == settings.jwt_secret)
email = "xingyuliu@outlook.sg"
print("user:", get_user_by_email(email))
token = create_token(email)
print("decode:", decode_token(token))
req = urllib.request.Request("http://127.0.0.1:8000/api/baskets", headers={"Authorization": "Bearer " + token})
try:
    print("list:", json.load(urllib.request.urlopen(req, timeout=30)))
except Exception as exc:
    print("FAIL", type(exc).__name__, getattr(exc, "code", ""), str(getattr(exc, "read", lambda: b"")())[:200])
