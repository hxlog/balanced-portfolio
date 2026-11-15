import json, sys, urllib.request, urllib.error
sys.path.insert(0, "/opt/balanced-portfolio")
sys.stdout.reconfigure(encoding="utf-8")
import jwt
from datetime import datetime, timedelta, timezone
env = {}
for line in open("/opt/balanced-portfolio/.env", encoding="utf-8"):
    line = line.strip()
    if not line or line.startswith("#") or "=" not in line: continue
    k, v = line.split("=", 1); env[k.strip()] = v.strip()
secret = env.get("BP_JWT_SECRET", "")
print("secret len:", len(secret))
from bp_ingest.config import load_config
from bp_ingest.db import connect
app = load_config()
with connect(app.db) as conn, conn.cursor() as cur:
    cur.execute("SELECT email, role, status FROM bp_user ORDER BY user_id LIMIT 5")
    for row in cur.fetchall(): print("user:", row)
    cur.execute("SELECT email FROM bp_user WHERE role='admin' LIMIT 1")
    email = cur.fetchone()[0]
token = jwt.encode({"sub": email, "role": "admin", "exp": datetime.now(timezone.utc) + timedelta(hours=1)}, secret, algorithm="HS256")
req = urllib.request.Request("http://127.0.0.1:8000/api/baskets", headers={"Authorization": "Bearer " + token})
try:
    print(json.load(urllib.request.urlopen(req, timeout=30)))
except urllib.error.HTTPError as exc:
    print("HTTP", exc.code, exc.read().decode()[:300])
