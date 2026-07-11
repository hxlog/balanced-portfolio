"""配置与管理员初始化的安全回归测试。"""

from __future__ import annotations

from contextlib import contextmanager
from types import SimpleNamespace

import pytest

from bp_api import auth
from bp_api.settings import load_settings
from bp_ingest.config import DBConfig, load_config


def test_database_defaults_are_local(monkeypatch):
    monkeypatch.delenv("PGHOST", raising=False)
    monkeypatch.delenv("PGDATABASE", raising=False)

    config = load_config()

    assert config.db.host == "127.0.0.1"
    assert config.db.dbname == "balanced_portfolio"


def test_auth_settings_use_generic_admin_and_independent_password(monkeypatch):
    monkeypatch.delenv("BP_ADMIN_EMAIL", raising=False)
    monkeypatch.setenv("BP_ADMIN_INITIAL_PASSWORD", "admin-only-secret")

    settings = load_settings()

    assert settings.admin_email == "admin@example.com"
    assert settings.admin_initial_password == "admin-only-secret"


def test_jwt_secret_must_be_explicit(monkeypatch):
    monkeypatch.delenv("BP_JWT_SECRET", raising=False)

    with pytest.raises(RuntimeError, match="BP_JWT_SECRET"):
        load_settings()


def test_jwt_secret_must_be_long_enough(monkeypatch):
    monkeypatch.setenv("BP_JWT_SECRET", "too-short")

    with pytest.raises(RuntimeError, match="32"):
        load_settings()


class _Cursor:
    def __init__(self, legacy_hash=None, user_hash=None, has_bp_user=True):
        self.legacy_hash = legacy_hash
        self.user_hash = user_hash
        self.has_bp_user = has_bp_user
        self.result = None
        self.executed: list[tuple[str, tuple | None]] = []

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        return False

    def execute(self, sql, params=None):
        self.executed.append((sql, params))
        normalized = " ".join(sql.split())
        if normalized.startswith("SELECT password_hash FROM bp_admin_user"):
            self.result = (self.legacy_hash,) if self.legacy_hash else None
        elif normalized.startswith("SELECT to_regclass"):
            self.result = ("bp_user",) if self.has_bp_user else (None,)
        elif normalized.startswith("SELECT password_hash FROM bp_user"):
            self.result = (self.user_hash,) if self.user_hash else None

    def fetchone(self):
        return self.result


class _Connection:
    def __init__(self, cursor):
        self._cursor = cursor
        self.committed = False

    def cursor(self):
        return self._cursor

    def commit(self):
        self.committed = True


def _mock_connection(monkeypatch, cursor):
    connection = _Connection(cursor)

    @contextmanager
    def get_conn():
        yield connection

    monkeypatch.setattr(auth.db, "get_conn", get_conn)
    return connection


def _settings(initial_password):
    return SimpleNamespace(
        admin_email="admin@example.com",
        admin_initial_password=initial_password,
        db=DBConfig("127.0.0.1", 5432, "balanced_portfolio", "postgres", "db-secret", 15),
    )


def test_existing_admin_does_not_require_initial_password(monkeypatch):
    cursor = _Cursor(legacy_hash="existing-hash")
    connection = _mock_connection(monkeypatch, cursor)
    monkeypatch.setattr(auth, "settings", _settings(None))

    auth.ensure_admin()

    assert connection.committed
    assert any(
        "INSERT INTO bp_user" in sql and params == ("admin@example.com", "existing-hash")
        for sql, params in cursor.executed
    )


def test_new_admin_uses_only_initial_password(monkeypatch):
    cursor = _Cursor()
    _mock_connection(monkeypatch, cursor)
    monkeypatch.setattr(auth, "settings", _settings("admin-only-secret"))
    hashed: list[str] = []
    monkeypatch.setattr(auth, "hash_password", lambda value: hashed.append(value) or "new-hash")

    auth.ensure_admin()

    assert hashed == ["admin-only-secret"]


def test_new_admin_without_initial_password_fails(monkeypatch):
    cursor = _Cursor()
    _mock_connection(monkeypatch, cursor)
    monkeypatch.setattr(auth, "settings", _settings(None))

    with pytest.raises(RuntimeError, match="BP_ADMIN_INITIAL_PASSWORD"):
        auth.ensure_admin()


def test_new_admin_rejects_short_initial_password(monkeypatch):
    cursor = _Cursor()
    _mock_connection(monkeypatch, cursor)
    monkeypatch.setattr(auth, "settings", _settings("short"))

    with pytest.raises(RuntimeError, match="12"):
        auth.ensure_admin()
