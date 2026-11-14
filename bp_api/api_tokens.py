"""对外 API token 的签发、校验、撤销与枚举。

设计要点（见 ``docs/index-valuation/06-data-model-v3.md`` §2.8）:

- 明文格式 ``bp_live_<32 hex>``，仅在 ``create_token`` 时返回一次；
- 库内只存 ``sha256(secret + pepper)``，pepper 来自 ``BP_API_TOKEN_PEPPER``，
  缺失时由 ``BP_JWT_SECRET`` 单向派生（绝不硬编码）；
- ``prefix`` 用于按前缀定位候选行（再做常量时间 hash 比较），因此取**随机段**
  的前 8 位：``bp_live_`` 恰好占满明文前 8 位，若按字面取「明文前 8 位」，
  所有 token 的 prefix 都相同，唯一键会直接冲突；
- 本模块只接受调用方传入的 ``conn``，不自行 commit —— 事务边界由端点/调用方掌握。
"""

from __future__ import annotations

import datetime as dt
import hashlib
import hmac
import os
import re
import secrets
from typing import Iterable, Optional, Sequence
from uuid import UUID

TOKEN_SCHEME = "bp_live_"
TOKEN_RANDOM_BYTES = 16  # token_hex(16) -> 32 个 hex 字符
TOKEN_PREFIX_LEN = 8
TOKEN_RE = re.compile(rf"^{re.escape(TOKEN_SCHEME)}[0-9a-f]{{32}}$")

ALLOWED_SCOPES: frozenset[str] = frozenset(
    {"quotes", "valuation", "percentile", "crypto", "portfolio"}
)

_PEPPER_FALLBACK_DOMAIN = "bp-api-token-pepper:v1:"


# ---------------------------------------------------------------------
# pepper / hash
# ---------------------------------------------------------------------
def _pepper() -> str:
    """返回 token pepper。

    优先 ``BP_API_TOKEN_PEPPER``；未配置时从 ``BP_JWT_SECRET`` 派生 ——
    两个值都不存在时显式失败，避免任何硬编码默认值。
    """
    pepper = os.getenv("BP_API_TOKEN_PEPPER", "").strip()
    if pepper:
        return pepper
    jwt_secret = os.getenv("BP_JWT_SECRET", "").strip()
    if not jwt_secret:
        raise RuntimeError(
            "必须设置 BP_API_TOKEN_PEPPER（或至少 BP_JWT_SECRET 以派生 pepper）"
        )
    return hashlib.sha256(
        f"{_PEPPER_FALLBACK_DOMAIN}{jwt_secret}".encode("utf-8")
    ).hexdigest()


def hash_token(plain: str, pepper: Optional[str] = None) -> str:
    """``sha256(secret + pepper)`` 的 hex digest；公开给测试/运维校验用。"""
    return hashlib.sha256(
        (plain + (pepper if pepper is not None else _pepper())).encode("utf-8")
    ).hexdigest()


def token_prefix(plain: str) -> str:
    """库内定位前缀 = 随机段前 8 位（见模块 docstring）。"""
    return plain[len(TOKEN_SCHEME) : len(TOKEN_SCHEME) + TOKEN_PREFIX_LEN]


# ---------------------------------------------------------------------
# 签发 / 校验 / 撤销 / 枚举
# ---------------------------------------------------------------------
def normalize_scopes(scopes: Iterable[str]) -> list[str]:
    """去重并校验 scope；非法值抛 ``ValueError``（API 层转 400）。"""
    values = [str(s).strip() for s in scopes if str(s).strip()]
    if not values:
        raise ValueError("scopes 不能为空")
    invalid = sorted(set(values) - ALLOWED_SCOPES)
    if invalid:
        raise ValueError(f"非法 scope: {', '.join(invalid)}")
    return list(dict.fromkeys(values))


def create_token(
    conn,
    name: str,
    scopes: Sequence[str],
    expires_at: Optional[dt.datetime],
    created_by: Optional[int],
) -> tuple[UUID, str]:
    """签发 token，返回 ``(token_id, plain_text)``；明文只在此处返回一次。"""
    name = (name or "").strip()
    if not name:
        raise ValueError("token 名称不能为空")
    normalized = normalize_scopes(scopes)

    secret = secrets.token_hex(TOKEN_RANDOM_BYTES)
    plain = f"{TOKEN_SCHEME}{secret}"
    with conn.cursor() as cur:
        cur.execute(
            """INSERT INTO bp_api_token
                   (name, prefix, token_hash, scopes, expires_at, created_by)
               VALUES (%s, %s, %s, %s, %s, %s)
               RETURNING token_id""",
            (name, token_prefix(plain), hash_token(plain), normalized, expires_at, created_by),
        )
        token_id = cur.fetchone()[0]
    return token_id, plain


def verify_token(conn, plain: str) -> Optional[dict]:
    """校验 token 并刷新 ``last_used_at``；无效时返回 ``None``。

    校验顺序：格式 → prefix 定位 → 常量时间 hash 比较 → 撤销 → 过期。
    更新 ``last_used_at`` 但不 commit（调用方决定事务边界）。
    """
    if not isinstance(plain, str):
        return None
    plain = plain.strip()
    if not TOKEN_RE.match(plain):
        return None

    candidate_hash = hash_token(plain)
    with conn.cursor() as cur:
        cur.execute(
            """SELECT token_id, name, scopes, token_hash, user_id, expires_at, revoked_at
               FROM bp_api_token
               WHERE prefix = %s""",
            (token_prefix(plain),),
        )
        row = cur.fetchone()
        if row is None:
            return None

        token_id, name, scopes, stored_hash, user_id, expires_at, revoked_at = row
        if not hmac.compare_digest(str(stored_hash).strip(), candidate_hash):
            return None
        if revoked_at is not None:
            return None
        if expires_at is not None and expires_at <= dt.datetime.now(dt.timezone.utc):
            return None

        cur.execute(
            "UPDATE bp_api_token SET last_used_at = now() WHERE token_id = %s",
            (token_id,),
        )
    return {
        "token_id": token_id,
        "name": name,
        "scopes": list(scopes or []),
        "user_id": user_id,
    }


def revoke_token(conn, token_id: UUID | str) -> bool:
    """撤销 token（幂等）；返回是否存在该 token。不 commit。"""
    with conn.cursor() as cur:
        cur.execute(
            """UPDATE bp_api_token
               SET revoked_at = COALESCE(revoked_at, now())
               WHERE token_id = %s""",
            (token_id,),
        )
        return cur.rowcount > 0


def list_tokens(conn) -> list[dict]:
    """列出 token 元数据（绝不返回 token_hash / 明文）。"""
    with conn.cursor() as cur:
        cur.execute(
            """SELECT token_id, name, prefix, scopes, user_id, expires_at,
                      revoked_at, last_used_at, created_by, created_at
               FROM bp_api_token
               ORDER BY created_at DESC, token_id DESC"""
        )
        rows = cur.fetchall()
    return [
        {
            "token_id": r[0],
            "name": r[1],
            "prefix": (r[2] or "").strip(),
            "scopes": list(r[3] or []),
            "user_id": r[4],
            "expires_at": r[5],
            "revoked_at": r[6],
            "last_used_at": r[7],
            "created_by": r[8],
            "created_at": r[9],
        }
        for r in rows
    ]
