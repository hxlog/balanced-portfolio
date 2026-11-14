"""对外 API token 集成测试（真实 bp_mig_test + 会话级 TEMP 表）。

迁移 56 尚未应用到 ``bp_mig_test`` 时，本文件在测试连接上创建同名 TEMP 表
（``pg_temp`` 优先于 ``public``，会话内遮蔽同名永久表），因此测试不依赖迁移执行，
也不会污染测试库的永久表。连接不可达时整文件 skip，与 ``test_repositories_valuation``
的口径一致。

TDD 覆盖点：明文只返回一次、库内只存 hash、前缀定位、过期/撤销/篡改、scope 403、
缺失或非法 token 401、列表不泄露明文、pepper 参与哈希且可从 JWT secret 派生。
"""

from __future__ import annotations

import datetime as dt
import hashlib
import re
from contextlib import contextmanager
from pathlib import Path
from uuid import UUID, uuid4

import psycopg
from types import SimpleNamespace

import pytest


class _ReqStub:
    """直接调用依赖函数时用的最小 Request 替身。"""

    def __init__(self) -> None:
        self.state = SimpleNamespace()


_REQ_STUB = _ReqStub()
from fastapi import HTTPException

from bp_api import api_tokens, auth, db as db_module, main
from bp_api.schemas import ApiTokenCreateIn

TEST_DB = {
    "host": "81.71.158.239",
    "port": 5432,
    "dbname": "bp_mig_test",
    "user": "postgres",
}
TEST_PEPPER = "unit-test-token-pepper-0123456789abcdef"
PLAIN_RE = re.compile(r"^bp_live_[0-9a-f]{32}$")

_CREATE_TEMP_TABLES = """
CREATE TEMP TABLE IF NOT EXISTS bp_api_token (
    token_id     UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    name         TEXT NOT NULL,
    prefix       CHAR(8) NOT NULL,
    token_hash   CHAR(64) NOT NULL,
    scopes       TEXT[] NOT NULL DEFAULT ARRAY['quotes']::TEXT[],
    user_id      BIGINT,
    expires_at   TIMESTAMPTZ,
    revoked_at   TIMESTAMPTZ,
    last_used_at TIMESTAMPTZ,
    created_by   BIGINT,
    created_at   TIMESTAMPTZ NOT NULL DEFAULT now(),
    CONSTRAINT uq_api_token_hash UNIQUE (token_hash),
    CONSTRAINT uq_api_token_prefix UNIQUE (prefix),
    CONSTRAINT ck_api_token_scopes
        CHECK (scopes <@ ARRAY['quotes','valuation','percentile','crypto','portfolio']::TEXT[])
);

CREATE TEMP TABLE IF NOT EXISTS bp_api_request_log (
    log_id     BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    token_id   UUID,
    path       TEXT NOT NULL,
    status     SMALLINT,
    latency_ms INTEGER,
    rows       INTEGER,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
"""


def _password() -> str:
    env_path = Path(__file__).resolve().parents[2] / ".env"
    if not env_path.exists():
        pytest.skip(".env 不存在，跳过 bp_mig_test 集成测试")
    for line in env_path.read_text(encoding="utf-8").splitlines():
        if line.startswith("PGPASSWORD="):
            return line.split("=", 1)[1].strip()
    pytest.skip("PGPASSWORD 不在 .env 中，跳过 bp_mig_test 集成测试")


def _connect() -> psycopg.Connection:
    try:
        return psycopg.connect(
            **TEST_DB,
            password=_password(),
            connect_timeout=8,
            autocommit=False,
        )
    except psycopg.Error as exc:  # pragma: no cover - 环境不可达时走 skip
        pytest.skip(f"bp_mig_test 不可达: {exc}")


@pytest.fixture(scope="module")
def conn():
    connection = _connect()
    with connection.cursor() as cur:
        cur.execute(_CREATE_TEMP_TABLES)
    connection.commit()
    yield connection
    connection.rollback()
    connection.close()


@pytest.fixture(autouse=True)
def _clean(conn, monkeypatch):
    monkeypatch.setenv("BP_API_TOKEN_PEPPER", TEST_PEPPER)
    conn.rollback()
    with conn.cursor() as cur:
        cur.execute("DELETE FROM bp_api_token")
        cur.execute("DELETE FROM bp_api_request_log")
    conn.commit()
    yield
    conn.rollback()
    with conn.cursor() as cur:
        cur.execute("DELETE FROM bp_api_token")
        cur.execute("DELETE FROM bp_api_request_log")
    conn.commit()


@pytest.fixture
def fixed_db(conn, monkeypatch):
    """让 auth/main 的 db.get_conn 复用测试连接（不初始化连接池）。"""

    @contextmanager
    def _get_conn():
        yield conn

    monkeypatch.setattr(db_module, "get_conn", _get_conn)
    return conn


def _create(conn, name="测试 token", scopes=("quotes",), expires_at=None):
    token_id, plain = api_tokens.create_token(conn, name, list(scopes), expires_at, None)
    conn.commit()
    return token_id, plain


def _row(conn, token_id):
    with conn.cursor() as cur:
        cur.execute(
            """SELECT token_id, name, prefix, token_hash, scopes, expires_at,
                      revoked_at, last_used_at, created_by, created_at
               FROM bp_api_token WHERE token_id=%s""",
            (token_id,),
        )
        return cur.fetchone()


# ---------------------------------------------------------------------
# 签发 / 存储
# ---------------------------------------------------------------------
def test_create_token_returns_plaintext_once_and_stores_only_hash(conn):
    token_id, plain = _create(conn, name="Excel 拉数", scopes=("quotes", "crypto"))

    assert isinstance(token_id, UUID)
    assert PLAIN_RE.match(plain)
    row = _row(conn, token_id)
    assert row is not None
    assert row[1] == "Excel 拉数"
    assert list(row[4]) == ["quotes", "crypto"]
    assert row[3].strip() == hashlib.sha256((plain + TEST_PEPPER).encode()).hexdigest()
    assert row[3].strip() != plain
    # 整行任何字段都不应出现明文（"只返回一次" 的存储侧保证）
    assert plain not in "".join("" if v is None else str(v) for v in row)


def test_prefix_is_unique_and_taken_from_random_part(conn):
    """bp_live_ 本身占满前 8 位，若取明文前 8 位则所有 token 前缀相同、唯一键必炸。

    因此 prefix = 随机段前 8 位（明文第 9~16 位），仅用于库内定位，不泄露秘密。
    """
    first_id, first = _create(conn, name="a")
    second_id, second = _create(conn, name="b")

    first_prefix = _row(conn, first_id)[2]
    second_prefix = _row(conn, second_id)[2]
    assert first_prefix != second_prefix
    assert first_prefix == first[8:16]
    assert second_prefix == second[8:16]
    assert len(first_prefix) == 8


def test_create_token_rejects_unknown_or_empty_scopes(conn):
    with pytest.raises(ValueError):
        api_tokens.create_token(conn, "bad", ["quotes", "admin"], None, None)
    with pytest.raises(ValueError):
        api_tokens.create_token(conn, "bad", [], None, None)
    with conn.cursor() as cur:
        cur.execute("SELECT count(*) FROM bp_api_token")
        assert cur.fetchone()[0] == 0


# ---------------------------------------------------------------------
# 校验
# ---------------------------------------------------------------------
def test_verify_token_returns_identity_and_updates_last_used_at(conn):
    token_id, plain = _create(conn, name="Python SDK", scopes=("quotes", "valuation"))
    assert _row(conn, token_id)[7] is None

    info = api_tokens.verify_token(conn, plain)
    conn.commit()

    assert info is not None
    assert info["token_id"] == token_id
    assert info["name"] == "Python SDK"
    assert info["scopes"] == ["quotes", "valuation"]
    assert _row(conn, token_id)[7] is not None


def test_verify_token_rejects_tampered_secret(conn):
    _, plain = _create(conn)
    tampered = plain[:-1] + ("0" if plain[-1] != "0" else "1")
    assert api_tokens.verify_token(conn, tampered) is None
    assert api_tokens.verify_token(conn, "not-a-token") is None


def test_verify_token_rejects_expired_token(conn):
    past = dt.datetime.now(dt.timezone.utc) - dt.timedelta(minutes=1)
    _, plain = _create(conn, expires_at=past)
    assert api_tokens.verify_token(conn, plain) is None


def test_verify_token_rejects_revoked_token(conn):
    token_id, plain = _create(conn)
    assert api_tokens.revoke_token(conn, token_id) is True
    conn.commit()
    assert api_tokens.verify_token(conn, plain) is None
    assert _row(conn, token_id)[6] is not None


def test_revoke_token_is_idempotent_and_reports_unknown(conn):
    token_id, _ = _create(conn)
    assert api_tokens.revoke_token(conn, token_id) is True
    assert api_tokens.revoke_token(conn, token_id) is True
    conn.commit()
    assert api_tokens.revoke_token(conn, uuid4()) is False


# ---------------------------------------------------------------------
# 列表
# ---------------------------------------------------------------------
def test_list_tokens_excludes_hash_and_plaintext(conn):
    first_id, first_plain = _create(conn, name="first")
    second_id, second_plain = _create(conn, name="second", scopes=("crypto",))
    conn.commit()

    tokens = api_tokens.list_tokens(conn)
    assert len(tokens) == 2
    by_id = {t["token_id"]: t for t in tokens}
    assert set(by_id) == {first_id, second_id}
    for token in tokens:
        assert "token_hash" not in token
        assert "plain_text" not in token
        assert "token" not in token
        assert token["prefix"] and len(token["prefix"]) == 8
        assert token["created_at"] is not None
    dumped = repr(tokens)
    assert first_plain not in dumped
    assert second_plain not in dumped


# ---------------------------------------------------------------------
# pepper
# ---------------------------------------------------------------------
def test_pepper_participates_in_hash_and_rotation_invalidates(conn, monkeypatch):
    _, plain = _create(conn)

    monkeypatch.setenv("BP_API_TOKEN_PEPPER", "a-different-pepper")
    assert api_tokens.verify_token(conn, plain) is None

    monkeypatch.setenv("BP_API_TOKEN_PEPPER", TEST_PEPPER)
    assert api_tokens.verify_token(conn, plain) is not None


def test_pepper_falls_back_to_jwt_secret_when_env_missing(conn, monkeypatch):
    monkeypatch.delenv("BP_API_TOKEN_PEPPER", raising=False)
    monkeypatch.setenv("BP_JWT_SECRET", "fallback-jwt-secret-for-tests-0123456789")

    token_id, plain = _create(conn)
    row = _row(conn, token_id)
    derived = hashlib.sha256(
        ("bp-api-token-pepper:v1:fallback-jwt-secret-for-tests-0123456789").encode()
    ).hexdigest()
    assert row[3].strip() == hashlib.sha256((plain + derived).encode()).hexdigest()
    assert api_tokens.verify_token(conn, plain) is not None


# ---------------------------------------------------------------------
# FastAPI 依赖
# ---------------------------------------------------------------------
def test_require_api_token_accepts_bearer_and_x_api_key(fixed_db):
    conn = fixed_db
    _, plain = _create(conn, name="dependency", scopes=("quotes", "portfolio"))
    dependency = auth.require_api_token("quotes")

    via_bearer = dependency(_REQ_STUB, authorization=f"Bearer {plain}", x_api_key="")
    via_header = dependency(_REQ_STUB, authorization="", x_api_key=plain)

    for info in (via_bearer, via_header):
        assert set(info) == {"token_id", "name", "scopes"}
        assert info["name"] == "dependency"
        assert info["scopes"] == ["quotes", "portfolio"]


def test_require_api_token_401_when_missing_or_invalid(fixed_db):
    dependency = auth.require_api_token()
    for kwargs in (
        {"authorization": "", "x_api_key": ""},
        {"authorization": "Basic abc", "x_api_key": ""},
        {"authorization": "Bearer bp_live_" + "0" * 32, "x_api_key": ""},
        {"authorization": "", "x_api_key": "bp_live_" + "f" * 32},
    ):
        with pytest.raises(HTTPException) as exc:
            dependency(_REQ_STUB, **kwargs)
        assert exc.value.status_code == 401


def test_require_api_token_403_when_scope_missing(fixed_db):
    conn = fixed_db
    _, plain = _create(conn, scopes=("quotes",))
    dependency = auth.require_api_token("valuation")

    with pytest.raises(HTTPException) as exc:
        dependency(_REQ_STUB, authorization=f"Bearer {plain}", x_api_key="")
    assert exc.value.status_code == 403


def test_require_api_token_401_after_revoke(fixed_db):
    conn = fixed_db
    token_id, plain = _create(conn)
    api_tokens.revoke_token(conn, token_id)
    conn.commit()
    dependency = auth.require_api_token("quotes")
    with pytest.raises(HTTPException) as exc:
        dependency(_REQ_STUB, authorization=f"Bearer {plain}", x_api_key="")
    assert exc.value.status_code == 401


# ---------------------------------------------------------------------
# 超管端点
# ---------------------------------------------------------------------
def test_admin_endpoints_create_list_and_revoke(fixed_db):
    conn = fixed_db
    admin = auth.UserContext(None, "admin@example.com", "admin", True)

    created = main.create_api_token(
        ApiTokenCreateIn(name="端点测试", scopes=["quotes", "crypto"]), admin
    )
    assert PLAIN_RE.match(created["plain_text"])
    token_id = UUID(str(created["token_id"]))
    assert created["name"] == "端点测试"
    assert created["scopes"] == ["quotes", "crypto"]

    listed = main.list_api_tokens(admin)
    assert len(listed["tokens"]) == 1
    assert listed["tokens"][0]["token_id"] == token_id
    assert "token_hash" not in listed["tokens"][0]

    revoked = main.revoke_api_token(token_id, admin)
    assert revoked["ok"] is True
    assert api_tokens.verify_token(conn, created["plain_text"]) is None

    with pytest.raises(HTTPException) as exc:
        main.revoke_api_token(uuid4(), admin)
    assert exc.value.status_code == 404


def test_admin_token_routes_registered_with_super_admin_dependency():
    required = {
        ("/api/admin/api-tokens", "POST"): main.create_api_token,
        ("/api/admin/api-tokens", "GET"): main.list_api_tokens,
        ("/api/admin/api-tokens/{token_id}", "DELETE"): main.revoke_api_token,
    }
    registered = {
        (route.path, method): route.endpoint
        for route in main.app.routes
        for method in getattr(route, "methods", set()) or set()
    }
    for key, endpoint in required.items():
        assert registered.get(key) is endpoint

    import inspect

    for endpoint in required.values():
        sig = inspect.signature(endpoint)
        dep = next(
            p.default for p in sig.parameters.values()
            if getattr(p.default, "dependency", None) is auth.require_super_admin
        )
        assert dep.dependency is auth.require_super_admin


# ---------------------------------------------------------------------
# DDL 静态检查（不执行迁移）
# ---------------------------------------------------------------------
def test_migration_ddl_declares_token_contract():
    path = Path(__file__).resolve().parents[2] / "ddl" / "56_api_tokens.sql"
    sql = path.read_text(encoding="utf-8")

    assert "bp_api_token" in sql
    assert "bp_api_request_log" in sql
    assert "token_hash   CHAR(64)" in sql or "token_hash CHAR(64)" in sql
    assert "prefix       CHAR(8)" in sql or "prefix CHAR(8)" in sql
    assert "ck_api_token_scopes" in sql
    for scope in ("quotes", "valuation", "percentile", "crypto", "portfolio"):
        assert f"'{scope}'" in sql
    assert "ON DELETE SET NULL" in sql
    assert "idx_api_log_time" in sql
    assert "created_at DESC" in sql
    # 不得存在明文列
    assert not re.search(r"\bplain_?text\b", sql, re.IGNORECASE)
