"""鉴权: bcrypt 密码哈希 + JWT(HS256) token + 管理员依赖。"""

from __future__ import annotations

import datetime as dt
from dataclasses import dataclass
from typing import Optional

import bcrypt
import jwt
import pyotp
from fastapi import Header, HTTPException

from . import cache
from . import db
from .settings import load_settings

settings = load_settings()


@dataclass(frozen=True)
class UserContext:
    user_id: Optional[int]
    email: str
    role: str
    is_admin: bool


# ---------------------------------------------------------------------
# 密码哈希
# ---------------------------------------------------------------------
def hash_password(password: str) -> str:
    return bcrypt.hashpw(password.encode("utf-8"), bcrypt.gensalt()).decode("utf-8")


def verify_password(password: str, password_hash: str) -> bool:
    try:
        return bcrypt.checkpw(password.encode("utf-8"), password_hash.encode("utf-8"))
    except (ValueError, TypeError):
        return False


# ---------------------------------------------------------------------
# JWT
# ---------------------------------------------------------------------
def create_token(email: str) -> str:
    now = dt.datetime.now(dt.timezone.utc)
    user = get_user_by_email(email)
    payload = {
        "sub": email,
        "uid": user.user_id if user else None,
        "role": user.role if user else ("admin" if is_super_admin(email) else "user"),
        "iat": now,
        "exp": now + dt.timedelta(hours=settings.jwt_expire_hours),
    }
    return jwt.encode(payload, settings.jwt_secret, algorithm="HS256")


def decode_token(token: str) -> Optional[str]:
    try:
        payload = jwt.decode(token, settings.jwt_secret, algorithms=["HS256"])
        return payload.get("sub")
    except jwt.PyJWTError:
        return None


def decode_token_with_grace(token: str, grace_hours: int = 24) -> Optional[str]:
    """解码 JWT; 过期后在 grace 窗口内仍视为有效(用于滑动续期)。"""
    try:
        payload = jwt.decode(token, settings.jwt_secret, algorithms=["HS256"])
        return payload.get("sub")
    except jwt.ExpiredSignatureError:
        try:
            payload = jwt.decode(
                token,
                settings.jwt_secret,
                algorithms=["HS256"],
                options={"verify_exp": False},
            )
            exp = payload.get("exp")
            if exp is None:
                return None
            expired_at = dt.datetime.fromtimestamp(exp, tz=dt.timezone.utc)
            if dt.datetime.now(dt.timezone.utc) - expired_at <= dt.timedelta(hours=grace_hours):
                return payload.get("sub")
        except jwt.PyJWTError:
            return None
    except jwt.PyJWTError:
        return None
    return None


def refresh_token(email: str) -> str:
    return create_token(email)


def is_super_admin(email: str) -> bool:
    return email == settings.admin_email


def _has_bp_user(conn) -> bool:
    with conn.cursor() as cur:
        cur.execute("SELECT to_regclass('public.bp_user')")
        return cur.fetchone()[0] is not None


def get_user_by_email(email: str) -> Optional[UserContext]:
    email = email.strip().lower()
    with db.get_conn() as conn:
        with conn.cursor() as cur:
            if _has_bp_user(conn):
                cur.execute(
                    "SELECT user_id, email, role, status FROM bp_user WHERE email=%s",
                    (email,),
                )
                row = cur.fetchone()
                if row and row[3] == "active":
                    role = "admin" if is_super_admin(row[1]) else row[2]
                    return UserContext(row[0], row[1], role, role == "admin")
            cur.execute("SELECT email FROM bp_admin_user WHERE email=%s", (email,))
            row = cur.fetchone()
            if row:
                role = "admin" if is_super_admin(email) else "user"
                return UserContext(None, email, role, role == "admin")
    return None


# ---------------------------------------------------------------------
# 账号操作
# ---------------------------------------------------------------------
def ensure_admin() -> None:
    """启动时确保超级管理员账号存在；仅首次创建时使用独立初始密码。"""
    with db.get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT password_hash FROM bp_admin_user WHERE email = %s",
                (settings.admin_email,),
            )
            legacy_row = cur.fetchone()

            has_bp_user = _has_bp_user(conn)
            user_row = None
            if has_bp_user:
                cur.execute(
                    "SELECT password_hash FROM bp_user WHERE email=%s",
                    (settings.admin_email,),
                )
                user_row = cur.fetchone()

            password_hash = (
                legacy_row[0] if legacy_row else user_row[0] if user_row else None
            )
            if password_hash is None:
                if not settings.admin_initial_password:
                    raise RuntimeError(
                        "管理员账号尚未创建，必须设置 BP_ADMIN_INITIAL_PASSWORD"
                    )
                if len(settings.admin_initial_password) < 12:
                    raise RuntimeError(
                        "BP_ADMIN_INITIAL_PASSWORD 至少需要 12 个字符"
                    )
                password_hash = hash_password(settings.admin_initial_password)

            if legacy_row is None:
                cur.execute(
                    "INSERT INTO bp_admin_user (email, password_hash) VALUES (%s, %s)",
                    (settings.admin_email, password_hash),
                )
            if has_bp_user:
                if user_row is None:
                    cur.execute(
                        """INSERT INTO bp_user (email, password_hash, role, status)
                           VALUES (%s,%s,'admin','active')""",
                        (settings.admin_email, password_hash),
                    )
                else:
                    cur.execute(
                        "UPDATE bp_user SET role='admin', status='active' WHERE email=%s",
                        (settings.admin_email,),
                    )
        conn.commit()


def user_exists(email: str) -> bool:
    return get_user_by_email(email) is not None


def authenticate(email: str, password: str) -> bool:
    email = email.strip().lower()
    with db.get_conn() as conn:
        with conn.cursor() as cur:
            if _has_bp_user(conn):
                cur.execute(
                    "SELECT password_hash, status FROM bp_user WHERE email = %s",
                    (email,),
                )
                row = cur.fetchone()
                if row:
                    return row[1] == "active" and verify_password(password, row[0])
            cur.execute("SELECT password_hash FROM bp_admin_user WHERE email = %s", (email,))
            row = cur.fetchone()
    return bool(row) and verify_password(password, row[0])


def authenticate_login(
    email: str,
    password: str,
    ip: str = "",
    otp_code: Optional[str] = None,
) -> dict:
    """带基础限流与 TOTP 二次验证的登录。

    人机验证已改为 TOTP 两步验证(China-friendly, 无境外依赖); 暴力破解由 Redis 限流防护。
    已开启 TOTP 的用户需提供 otp_code; 管理员若尚未绑定, 登录后由前端强制引导绑定。
    """
    email = email.strip().lower()
    if not authenticate(email, password):
        ip_fail = cache.incr_with_ttl(f"login:fail:ip:{ip or 'unknown'}", 900)
        email_fail = cache.incr_with_ttl(f"login:fail:email:{email}", 900)
        if ip_fail > 20 or email_fail > 10:
            raise HTTPException(429, "登录尝试过于频繁, 请稍后再试")
        raise HTTPException(401, "邮箱或密码不正确")

    with db.get_conn() as conn:
        with conn.cursor() as cur:
            if _has_bp_user(conn):
                cur.execute(
                    "SELECT totp_enabled, totp_secret FROM bp_user WHERE email=%s",
                    (email,),
                )
                row = cur.fetchone()
                if row and row[0]:
                    if not otp_code:
                        return {"requires_2fa": True, "email": email}
                    if not row[1] or not pyotp.TOTP(row[1]).verify(otp_code, valid_window=1):
                        raise HTTPException(401, "二次验证码不正确")

    return {"token": create_token(email), "email": email}


def totp_enabled(email: str) -> bool:
    """该用户是否已启用 TOTP 两步验证。"""
    email = email.strip().lower()
    with db.get_conn() as conn:
        if not _has_bp_user(conn):
            return False
        with conn.cursor() as cur:
            cur.execute("SELECT totp_enabled FROM bp_user WHERE email=%s", (email,))
            row = cur.fetchone()
    return bool(row and row[0])


def change_password(email: str, old_password: str, new_password: str) -> None:
    with db.get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT password_hash FROM bp_admin_user WHERE email = %s", (email,))
            row = cur.fetchone()
            if not row or not verify_password(old_password, row[0]):
                raise HTTPException(400, "原密码不正确")
            cur.execute(
                "UPDATE bp_admin_user SET password_hash = %s WHERE email = %s",
                (hash_password(new_password), email),
            )
        conn.commit()


def list_users() -> list[dict]:
    with db.get_conn() as conn:
        with conn.cursor() as cur:
            if _has_bp_user(conn):
                cur.execute(
                    """SELECT u.email, u.created_at, u.role, u.status, u.portfolio_limit,
                              COUNT(p.portfolio_id) FILTER (WHERE p.is_demo = FALSE) AS portfolio_count
                       FROM bp_user u
                       LEFT JOIN bp_portfolio p ON p.owner_user_id = u.user_id
                       GROUP BY u.user_id, u.email, u.created_at, u.role, u.status, u.portfolio_limit
                       ORDER BY u.created_at ASC""",
                )
                rows = cur.fetchall()
                return [
                    {
                        "email": r[0],
                        "created_at": r[1].isoformat() if r[1] else None,
                        "role": "admin" if is_super_admin(r[0]) else r[2],
                        "status": r[3],
                        "portfolio_limit": None if (is_super_admin(r[0]) or r[2] == "admin") else r[4],
                        "portfolio_count": int(r[5] or 0),
                        "is_super_admin": is_super_admin(r[0]) or r[2] == "admin",
                    }
                    for r in rows
                ]
            cur.execute("SELECT email, created_at FROM bp_admin_user ORDER BY created_at ASC")
            rows = cur.fetchall()
    return [
        {
            "email": r[0],
            "created_at": r[1].isoformat() if r[1] else None,
            "is_super_admin": is_super_admin(r[0]),
        }
        for r in rows
    ]


def create_user(email: str, password: str) -> None:
    email = email.strip().lower()
    if not email or not password:
        raise HTTPException(400, "邮箱与密码不能为空")
    if user_exists(email):
        raise HTTPException(409, "该邮箱已存在")
    with db.get_conn() as conn:
        with conn.cursor() as cur:
            if _has_bp_user(conn):
                cur.execute(
                    """INSERT INTO bp_user (email, password_hash, role, status)
                       VALUES (%s,%s,'user','active')""",
                    (email, hash_password(password)),
                )
            cur.execute(
                "INSERT INTO bp_admin_user (email, password_hash) VALUES (%s, %s) ON CONFLICT DO NOTHING",
                (email, hash_password(password)),
            )
        conn.commit()


def update_user(email: str, portfolio_limit: Optional[int] = None, status: Optional[str] = None) -> None:
    email = email.strip().lower()
    if is_super_admin(email):
        raise HTTPException(400, "不能修改超级管理员限制")
    with db.get_conn() as conn:
        if not _has_bp_user(conn):
            raise HTTPException(400, "请先执行平台升级 DDL")
        with conn.cursor() as cur:
            cur.execute("SELECT 1 FROM bp_user WHERE email=%s", (email,))
            if cur.fetchone() is None:
                raise HTTPException(404, "用户不存在")
            if portfolio_limit is not None:
                if portfolio_limit < 0:
                    raise HTTPException(400, "组合上限不能为负数")
                cur.execute(
                    "UPDATE bp_user SET portfolio_limit=%s WHERE email=%s",
                    (portfolio_limit, email),
                )
            if status is not None:
                if status not in ("active", "disabled"):
                    raise HTTPException(400, "用户状态非法")
                cur.execute("UPDATE bp_user SET status=%s WHERE email=%s", (status, email))
        conn.commit()


def delete_user(email: str, actor_email: str) -> None:
    email = email.strip().lower()
    if email == actor_email:
        raise HTTPException(400, "不能删除当前登录账号")
    if is_super_admin(email):
        raise HTTPException(400, "不能删除超级管理员账号")
    with db.get_conn() as conn:
        with conn.cursor() as cur:
            if _has_bp_user(conn):
                cur.execute("UPDATE bp_user SET status='disabled' WHERE email=%s", (email,))
            cur.execute("DELETE FROM bp_admin_user WHERE email = %s", (email,))
            if cur.rowcount == 0:
                if not _has_bp_user(conn):
                    raise HTTPException(404, "用户不存在")
        conn.commit()


# ---------------------------------------------------------------------
# FastAPI 依赖
# ---------------------------------------------------------------------
def _email_from_auth_header(authorization: str) -> str:
    if not authorization.lower().startswith("bearer "):
        raise HTTPException(401, "需要登录")
    token = authorization.split(" ", 1)[1].strip()
    email = decode_token(token)
    if not email:
        raise HTTPException(401, "登录已失效或无权限")
    return email


def optional_user(authorization: str = Header(default="")) -> Optional[UserContext]:
    if not authorization:
        return None
    email = _email_from_auth_header(authorization).strip().lower()
    return get_user_by_email(email)


def require_user(authorization: str = Header(default="")) -> UserContext:
    """校验 Bearer token; 白名单用户均可通过。失败抛 401。"""
    email = _email_from_auth_header(authorization).strip().lower()
    user = get_user_by_email(email)
    if not user:
        raise HTTPException(401, "登录已失效或无权限")
    return user


def require_admin(authorization: str = Header(default="")) -> UserContext:
    return require_user(authorization)


def require_super_admin(authorization: str = Header(default="")) -> UserContext:
    """超级管理员专用依赖。"""
    user = require_user(authorization)
    if not user.is_admin:
        raise HTTPException(403, "需要超级管理员权限")
    return user


def auth_profile(user: UserContext | str) -> dict:
    if isinstance(user, str):
        user = get_user_by_email(user) or UserContext(None, user, "user", False)
    has_2fa = totp_enabled(user.email)
    return {
        "user_id": user.user_id,
        "email": user.email,
        # 任意白名单用户均可创建/编辑自己的组合
        "is_whitelisted": True,
        # 是否真实管理员(可见全部组合、管理用户/资产/示例)
        "is_super_admin": user.is_admin,
        "role": user.role,
        "totp_enabled": has_2fa,
        # 管理员尚未绑定 TOTP 时, 前端强制其先绑定
        "must_setup_2fa": user.is_admin and not has_2fa,
    }


def _verify_totp_secret(secret: str, code: str) -> bool:
    return bool(secret and pyotp.TOTP(secret).verify(code, valid_window=1))


def setup_totp(email: str, current_code: Optional[str] = None) -> dict:
    email = email.strip().lower()
    with db.get_conn() as conn:
        if not _has_bp_user(conn):
            raise HTTPException(400, "请先执行平台升级 DDL")
        with conn.cursor() as cur:
            cur.execute(
                "SELECT totp_enabled, totp_secret FROM bp_user WHERE email=%s",
                (email,),
            )
            row = cur.fetchone()
            if not row:
                raise HTTPException(404, "用户不存在")
            enabled, secret = bool(row[0]), row[1]
            if enabled:
                if not current_code:
                    raise HTTPException(409, "已绑定两步验证，请通过管理流程换绑")
                if not _verify_totp_secret(secret, current_code):
                    raise HTTPException(400, "当前验证码不正确")
            secret = pyotp.random_base32()
            cur.execute(
                "UPDATE bp_user SET totp_secret=%s, totp_enabled=FALSE WHERE email=%s",
                (secret, email),
            )
        conn.commit()
    uri = pyotp.totp.TOTP(secret).provisioning_uri(name=email, issuer_name="Balanced Portfolio")
    return {"secret": secret, "otpauth_url": uri}


def enable_totp(email: str, code: str) -> None:
    email = email.strip().lower()
    with db.get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT totp_secret FROM bp_user WHERE email=%s", (email,))
            row = cur.fetchone()
            if not row or not _verify_totp_secret(row[0], code):
                raise HTTPException(400, "验证码不正确")
            cur.execute("UPDATE bp_user SET totp_enabled=TRUE WHERE email=%s", (email,))
        conn.commit()


def disable_totp(email: str, code: str) -> None:
    email = email.strip().lower()
    user = get_user_by_email(email)
    if not user:
        raise HTTPException(404, "用户不存在")
    if user.is_admin:
        raise HTTPException(403, "管理员须保持两步验证")
    with db.get_conn() as conn:
        if not _has_bp_user(conn):
            raise HTTPException(400, "请先执行平台升级 DDL")
        with conn.cursor() as cur:
            cur.execute(
                "SELECT totp_enabled, totp_secret FROM bp_user WHERE email=%s",
                (email,),
            )
            row = cur.fetchone()
            if not row or not row[0]:
                raise HTTPException(400, "尚未启用两步验证")
            if not _verify_totp_secret(row[1], code):
                raise HTTPException(400, "验证码不正确")
            cur.execute(
                "UPDATE bp_user SET totp_enabled=FALSE, totp_secret=NULL WHERE email=%s",
                (email,),
            )
        conn.commit()
