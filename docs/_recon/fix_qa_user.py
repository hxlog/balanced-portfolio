# -*- coding: utf-8 -*-
"""在服务器上创建/修复 QA 测试账号（bcrypt 由 Python 生成，避免 shell 引号问题）。"""
import sys
sys.path.insert(0, "/opt/balanced-portfolio")
sys.stdout.reconfigure(encoding="utf-8")
import bcrypt
from bp_ingest.config import load_config
from bp_ingest.db import connect

EMAIL = "qa-bot@example.com"
PASSWORD = b"QaBot!2026Test"
app = load_config()
hashed = bcrypt.hashpw(PASSWORD, bcrypt.gensalt(rounds=12)).decode()
with connect(app.db) as conn, conn.cursor() as cur:
    cur.execute("SELECT user_id FROM bp_user WHERE email = %s", (EMAIL,))
    row = cur.fetchone()
    if row:
        cur.execute("UPDATE bp_user SET password_hash = %s, status = %s, role = %s WHERE email = %s", (hashed, "active", "user", EMAIL))
    else:
        cur.execute(
            "INSERT INTO bp_user (email, password_hash, role, status, totp_enabled, can_manage_assets, portfolio_limit) VALUES (%s, %s, %s, %s, false, true, 10)",
            (EMAIL, hashed, "user", "active"),
        )
    conn.commit()
    cur.execute("SELECT user_id, email, role, status FROM bp_user WHERE email = %s", (EMAIL,))
    print(cur.fetchone())
print("hash len:", len(hashed), "verify:", bcrypt.checkpw(PASSWORD, hashed.encode()))
