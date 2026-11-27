"""ddl/78 + bp_api/baskets.py：示例篮子权限 / 匿名可读 / 复制 / 服务端重算。

不连数据库：db.get_conn 与 repositories.load_price_panel 用 FakeConn 打桩；
路由测试直接调用 register_routes 注册后的 endpoint 函数（与 test_basket.py 约定一致）。
"""
from __future__ import annotations

import importlib.util
import inspect
import re
import sys
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace

import numpy as np
import pandas as pd
import pytest
from fastapi import FastAPI, HTTPException

from bp_api import auth, baskets

ROOT = Path(__file__).resolve().parents[2]

USER1 = auth.UserContext(user_id=1, email="u1@example.com", role="user", is_admin=False)
USER2 = auth.UserContext(user_id=2, email="u2@example.com", role="user", is_admin=False)
ADMIN = auth.UserContext(user_id=9, email="admin@example.com", role="admin", is_admin=True)

_COLUMNS = (
    "basket_id",
    "owner_user_id",
    "name",
    "description",
    "method",
    "assets",
    "params",
    "latest_result",
    "is_demo",
    "display_order",
    "created_at",
    "updated_at",
)
_NOW = datetime(2026, 11, 27, 12, 0, tzinfo=timezone.utc)


def _unwrap(value):
    return getattr(value, "obj", value)


def _row(
    basket_id: int,
    *,
    owner: int | None = 1,
    name: str | None = None,
    is_demo: bool = False,
    display_order: int | None = None,
    updated_at: datetime | None = None,
    latest_result: dict | None = None,
    method: str = "risk_parity",
) -> dict:
    return {
        "basket_id": basket_id,
        "owner_user_id": owner,
        "name": name or "篮子{0}".format(basket_id),
        "description": None,
        "method": method,
        "assets": [{"symbol": "600519", "source": "etl_a_stock"}],
        "params": {"lookback_days": 60},
        "latest_result": latest_result,
        "is_demo": is_demo,
        "display_order": display_order,
        "created_at": _NOW,
        "updated_at": updated_at or _NOW,
    }


class _State:
    def __init__(self, rows: list[dict]) -> None:
        self.rows = rows
        self.next_id = max((row["basket_id"] for row in rows), default=0) + 1
        self.queries: list[tuple[str, object]] = []
        self.commits = 0


class _FakeCursor:
    def __init__(self, conn: "_FakeConn") -> None:
        self.conn = conn
        self._rows: list = []
        self.description: list = []
        self.rowcount = 0

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def _select(self, sql: str, params) -> None:
        state = self.conn.state
        match = re.search(r"SELECT (.+?) FROM bp_basket", sql, re.S)
        columns = [c.strip() for c in match.group(1).split(",")] if match else list(_COLUMNS)
        self.description = [SimpleNamespace(name=col) for col in columns]
        if "WHERE basket_id = %s" in sql:
            target = next((row for row in state.rows if row["basket_id"] == params[0]), None)
            selected = [target] if target else []
        elif "WHERE owner_user_id = %s AND is_demo = FALSE" in sql:
            selected = [r for r in state.rows if r["owner_user_id"] == params[0] and not r["is_demo"]]
        elif "WHERE is_demo = TRUE OR owner_user_id = %s" in sql:
            selected = [r for r in state.rows if r["is_demo"] or r["owner_user_id"] == params[0]]
        elif "WHERE is_demo = TRUE" in sql:
            selected = [r for r in state.rows if r["is_demo"]]
        else:
            selected = list(state.rows)
        if "ORDER BY is_demo DESC" in sql:
            selected = sorted(
                selected,
                key=lambda r: (
                    not r["is_demo"],
                    r["display_order"] if r["display_order"] is not None else 10**9,
                    -r["updated_at"].timestamp(),
                ),
            )
        elif "ORDER BY display_order ASC NULLS LAST" in sql:
            selected = sorted(
                selected,
                key=lambda r: (
                    r["display_order"] if r["display_order"] is not None else 10**9,
                    r["basket_id"],
                ),
            )
        elif "ORDER BY updated_at DESC" in sql:
            selected = sorted(selected, key=lambda r: (-r["updated_at"].timestamp(), -r["basket_id"]))
        self._rows = [tuple(row.get(col) for col in columns) for row in selected]

    def execute(self, sql: str, params=None) -> None:
        text = " ".join(str(sql).split())
        self.conn.state.queries.append((text, params))
        state = self.conn.state
        self._rows = []
        self.description = []
        self.rowcount = 0
        if text.startswith("SELECT") and "FROM bp_basket" in text:
            self._select(text, params or ())
        elif text.startswith("INSERT INTO bp_basket"):
            payload = [_unwrap(value) for value in params]
            new_row = _row(state.next_id, owner=payload[0])
            new_row.update(
                {
                    "name": payload[1],
                    "description": payload[2],
                    "method": payload[3],
                    "assets": payload[4],
                    "params": payload[5],
                    "latest_result": payload[6],
                    "is_demo": False,
                    "display_order": None,
                }
            )
            state.rows.append(new_row)
            state.next_id += 1
            if "created_at" in text:
                self._rows = [(new_row["basket_id"], new_row["created_at"], new_row["updated_at"])]
            else:
                self._rows = [(new_row["basket_id"],)]
        elif text.startswith("UPDATE bp_basket"):
            self._update(text, params or ())
        elif text.startswith("DELETE FROM bp_basket"):
            before = len(state.rows)
            state.rows = [r for r in state.rows if r["basket_id"] != params[0]]
            self.rowcount = before - len(state.rows)
        else:
            self._rows = []

    def _update(self, text: str, params) -> None:
        state = self.conn.state
        body = text.split(" SET ", 1)[1].split(" WHERE ", 1)[0]
        fragments = [f.strip() for f in body.split(",")]
        basket_id = params[-1]
        target = next((row for row in state.rows if row["basket_id"] == basket_id), None)
        if target is None:
            self._rows = []
            return
        values = list(params[:-1])
        vi = 0
        for fragment in fragments:
            if "now()" in fragment:
                target["updated_at"] = datetime.now(timezone.utc)
                continue
            column = fragment.split(" = ")[0].strip()
            target[column] = _unwrap(values[vi])
            vi += 1
        if "RETURNING updated_at" in text:
            self._rows = [(target["updated_at"],)]

    def executemany(self, sql: str, payload) -> None:
        raise AssertionError("baskets 路由不应批量写库")

    def fetchone(self):
        return self._rows[0] if self._rows else None

    def fetchall(self) -> list:
        return self._rows


class _FakeConn:
    def __init__(self, state: _State) -> None:
        self.state = state

    def cursor(self) -> _FakeCursor:
        return _FakeCursor(self)

    def commit(self) -> None:
        self.state.commits += 1


@pytest.fixture
def routes() -> dict[tuple[str, str], object]:
    app = FastAPI()
    baskets.register_routes(app)
    return {
        (getattr(route, "path", None), method.upper()): route.endpoint
        for route in app.routes
        for method in getattr(route, "methods", set())
    }


@pytest.fixture
def panel() -> pd.DataFrame:
    dates = [d.date() for d in pd.bdate_range("2022-01-03", periods=400)]
    rng = np.random.default_rng(11)
    return pd.DataFrame(
        {
            "600519@etl_a_stock": 100 * np.exp(np.cumsum(rng.normal(0.0004, 0.012, 400))),
            "300750@etl_a_stock": 100 * np.exp(np.cumsum(rng.normal(0.0005, 0.016, 400))),
            "600036@etl_a_stock": 100 * np.exp(np.cumsum(rng.normal(0.0002, 0.009, 400))),
        },
        index=dates,
    )


def _bind(monkeypatch, state: _State, panel: pd.DataFrame | None = None) -> _FakeConn:
    conn = _FakeConn(state)

    @contextmanager
    def fake_get_conn():
        yield conn

    monkeypatch.setattr(baskets.db, "get_conn", fake_get_conn)
    if panel is not None:

        def fake_load(c, pairs):
            return panel.copy()
        monkeypatch.setattr(baskets.repo, "load_price_panel", fake_load)
    return conn


def _state() -> _State:
    return _State(
        [
            _row(1, owner=None, name="示例A", is_demo=True, display_order=0),
            _row(2, owner=1, name="用户1私有"),
            _row(3, owner=2, name="用户2私有"),
            _row(4, owner=None, name="示例B", is_demo=True, display_order=1),
        ]
    )


# ---------------------------------------------------------------------------
# 1. 纯权限函数（与前端 web/lib/basket-demo.ts 同口径）
# ---------------------------------------------------------------------------
def test_can_view_demo_anonymous_and_private_matrix():
    demo = _row(1, owner=None, is_demo=True)
    private = _row(2, owner=1)
    assert baskets._can_view(demo, None) is True
    assert baskets._can_view(private, None) is False
    assert baskets._can_view(private, USER1) is True
    assert baskets._can_view(private, USER2) is False
    assert baskets._can_view(private, ADMIN) is True


def test_can_edit_demo_is_admin_only_but_own_private_editable():
    demo = _row(1, owner=1, is_demo=True)  # 即便 owner 是普通用户，示例也不可改
    private = _row(2, owner=1)
    assert baskets._can_edit(demo, None) is False
    assert baskets._can_edit(demo, USER1) is False
    assert baskets._can_edit(demo, ADMIN) is True
    assert baskets._can_edit(private, USER1) is True
    assert baskets._can_edit(private, USER2) is False
    assert baskets._can_edit(private, ADMIN) is True


# ---------------------------------------------------------------------------
# 2. 列表：匿名示例 / 登录示例+自己 / admin 全部
# ---------------------------------------------------------------------------
def test_list_anonymous_returns_only_demo(routes, monkeypatch):
    _bind(monkeypatch, _state())
    body = routes[("/api/baskets", "GET")](None, None)
    ids = [row["basket_id"] for row in body["data"]]
    assert ids == [1, 4]
    assert all(row["is_demo"] for row in body["data"])
    assert body["meta"]["rows"] == 2


def test_list_anonymous_scope_mine_is_empty_list_not_401(routes, monkeypatch):
    _bind(monkeypatch, _state())
    body = routes[("/api/baskets", "GET")]("mine", None)
    assert body["data"] == []


def test_list_logged_in_returns_demo_plus_own(routes, monkeypatch):
    _bind(monkeypatch, _state())
    body = routes[("/api/baskets", "GET")](None, USER1)
    ids = [row["basket_id"] for row in body["data"]]
    assert ids == [1, 4, 2]
    assert 3 not in ids


def test_list_admin_returns_all(routes, monkeypatch):
    _bind(monkeypatch, _state())
    body = routes[("/api/baskets", "GET")](None, ADMIN)
    assert {row["basket_id"] for row in body["data"]} == {1, 2, 3, 4}


def test_list_scope_filters(routes, monkeypatch):
    _bind(monkeypatch, _state())
    demo = routes[("/api/baskets", "GET")]("demo", USER1)
    assert [row["basket_id"] for row in demo["data"]] == [1, 4]
    mine = routes[("/api/baskets", "GET")]("mine", USER1)
    assert [row["basket_id"] for row in mine["data"]] == [2]


def test_list_unknown_scope_returns_400(routes, monkeypatch):
    _bind(monkeypatch, _state())
    with pytest.raises(HTTPException) as exc:
        routes[("/api/baskets", "GET")]("bogus", None)
    assert exc.value.status_code == 400


def test_list_rows_include_is_demo_and_display_order(routes, monkeypatch):
    _bind(monkeypatch, _state())
    rows = routes[("/api/baskets", "GET")](None, None)["data"]
    demo = next(row for row in rows if row["basket_id"] == 1)
    assert demo["is_demo"] is True
    assert demo["display_order"] == 0


# ---------------------------------------------------------------------------
# 3. 详情 / 复制
# ---------------------------------------------------------------------------
def test_get_demo_anonymous_allowed_but_private_forbidden(routes, monkeypatch):
    _bind(monkeypatch, _state())
    get_ep = routes[("/api/baskets/{basket_id}", "GET")]
    body = get_ep(1, None)
    assert body["data"]["basket_id"] == 1
    with pytest.raises(HTTPException) as exc:
        get_ep(2, None)
    assert exc.value.status_code == 403
    with pytest.raises(HTTPException) as exc404:
        get_ep(999, None)
    assert exc404.value.status_code == 404


def test_copy_requires_login_dependency(routes):
    signature = inspect.signature(routes[("/api/baskets/{basket_id}/copy", "POST")])
    dependency = signature.parameters["user"].default
    assert getattr(dependency, "dependency", None) is auth.require_user


def test_copy_demo_creates_private_copy_for_logged_in_user(routes, monkeypatch):
    state = _state()
    state.rows[0]["latest_result"] = {"annualized_return": 0.1}
    _bind(monkeypatch, state)
    body = routes[("/api/baskets/{basket_id}/copy", "POST")](1, None, USER1)
    new_id = body["data"]["basket_id"]
    created = next(row for row in state.rows if row["basket_id"] == new_id)
    assert created["owner_user_id"] == USER1.user_id
    assert created["is_demo"] is False
    assert created["assets"] == state.rows[0]["assets"]
    assert created["latest_result"] == {"annualized_return": 0.1}
    assert state.commits >= 1


# ---------------------------------------------------------------------------
# 4. 编辑 / 删除：示例仅 admin
# ---------------------------------------------------------------------------
def test_update_demo_by_non_admin_owner_forbidden_admin_allowed(routes, monkeypatch):
    state = _State([_row(1, owner=USER1.user_id, is_demo=True)])
    _bind(monkeypatch, state)
    patch_ep = routes[("/api/baskets/{basket_id}", "PATCH")]
    payload = baskets.BasketUpdateIn(name="改名")
    with pytest.raises(HTTPException) as exc:
        patch_ep(1, payload, USER1)
    assert exc.value.status_code == 403
    body = patch_ep(1, payload, ADMIN)
    assert body["data"]["basket_id"] == 1
    assert state.rows[0]["name"] == "改名"


def test_update_demo_latest_result_rejected_until_recompute(routes, monkeypatch):
    state = _State([_row(1, owner=None, is_demo=True)])
    _bind(monkeypatch, state)
    patch_ep = routes[("/api/baskets/{basket_id}", "PATCH")]
    payload = baskets.BasketUpdateIn(latest_result={"annualized_return": 99.0})
    with pytest.raises(HTTPException) as exc:
        patch_ep(1, payload, ADMIN)
    assert exc.value.status_code == 400
    assert "recompute" in str(exc.value.detail)
    assert state.rows[0]["latest_result"] is None


def test_create_ignores_client_supplied_latest_result(routes, monkeypatch):
    """P2：POST /api/baskets 必须忽略客户端伪造的 latest_result。"""
    state = _State([])
    _bind(monkeypatch, state)
    payload = baskets.BasketSaveIn(
        name="伪造结果",
        assets=[{"symbol": "600519", "source": "etl_a_stock"}],
        latest_result={"annualized_return": 9.99},
    )
    body = routes[("/api/baskets", "POST")](payload, USER1)
    created_id = body["data"]["basket_id"]
    created = next(row for row in state.rows if row["basket_id"] == created_id)
    assert created["latest_result"] is None, "创建时客户端 latest_result 必须被忽略"


def test_patch_demo_definition_change_clears_latest_result(routes, monkeypatch):
    """P2：示例篮子定义变更后旧 latest_result 置 NULL；仅改名不清空。"""
    existing = {"annualized_return": 0.1}
    state = _State([_row(1, owner=None, is_demo=True, latest_result=dict(existing))])
    _bind(monkeypatch, state)
    patch_ep = routes[("/api/baskets/{basket_id}", "PATCH")]

    body = patch_ep(1, baskets.BasketUpdateIn(params={"lookback_days": 90}), ADMIN)
    assert body["data"]["basket_id"] == 1
    assert state.rows[0]["latest_result"] is None, "定义变更后旧结果必须失效"

    # 仅改 name 不属于定义变更：latest_result 保留
    state2 = _State([_row(1, owner=None, is_demo=True, latest_result=dict(existing))])
    _bind(monkeypatch, state2)
    patch_ep(1, baskets.BasketUpdateIn(name="仅改名"), ADMIN)
    assert state2.rows[0]["latest_result"] == existing
def test_update_own_private_basket_allowed(routes, monkeypatch):
    state = _State([_row(2, owner=USER1.user_id)])
    _bind(monkeypatch, state)
    patch_ep = routes[("/api/baskets/{basket_id}", "PATCH")]
    body = patch_ep(2, baskets.BasketUpdateIn(name="我的新名字"), USER1)
    assert body["data"]["basket_id"] == 2
    assert state.rows[0]["name"] == "我的新名字"


def test_delete_demo_non_admin_forbidden_admin_allowed(routes, monkeypatch):
    state = _State([_row(1, owner=None, is_demo=True), _row(2, owner=USER1.user_id)])
    _bind(monkeypatch, state)
    delete_ep = routes[("/api/baskets/{basket_id}", "DELETE")]
    with pytest.raises(HTTPException) as exc:
        delete_ep(1, USER1)
    assert exc.value.status_code == 403
    body = delete_ep(1, ADMIN)
    assert body["data"]["deleted"] is True
    assert not any(row["basket_id"] == 1 for row in state.rows)


# ---------------------------------------------------------------------------
# 5. 服务端重算
# ---------------------------------------------------------------------------
def test_recompute_declares_super_admin_dependency(routes):
    signature = inspect.signature(routes[("/api/baskets/{basket_id}/recompute", "POST")])
    dependency = signature.parameters["user"].default
    assert getattr(dependency, "dependency", None) is auth.require_super_admin


def _recompute_state() -> _State:
    row = _row(1, owner=None, is_demo=True)
    row["assets"] = [
        {"symbol": "600519", "source": "etl_a_stock"},
        {"symbol": "300750", "source": "etl_a_stock"},
        {"symbol": "600036", "source": "etl_a_stock"},
    ]
    row["params"] = {"lookback_days": 60, "rebalance_band": 0.05}
    return _State([row])


def test_recompute_writes_latest_result_from_server_side_backtest(routes, monkeypatch, panel):
    state = _recompute_state()
    _bind(monkeypatch, state, panel)
    body = routes[("/api/baskets/{basket_id}/recompute", "POST")](1, ADMIN)
    summary = body["data"]["latest_result"]
    assert body["data"]["basket_id"] == 1
    assert isinstance(summary["annualized_return"], float)
    assert isinstance(summary["max_drawdown"], float)
    assert isinstance(summary["sharpe"], float)
    assert summary["method"] == "risk_parity"
    assert summary["n_obs"] > 100
    assert len(summary["nav"]) > 100
    assert abs(sum(weight["weight"] for weight in summary["weights"]) - 1.0) < 1e-6
    stored = state.rows[0]["latest_result"]
    assert stored is not None and stored["annualized_return"] == summary["annualized_return"]
    assert state.commits >= 1


def test_recompute_missing_quotes_returns_404_without_overwrite(routes, monkeypatch):
    state = _recompute_state()

    @contextmanager
    def fake_get_conn():
        yield _FakeConn(state)

    def fail(conn, pairs):
        raise ValueError("600519@etl_a_stock 无清洗行情数据, 请先运行 ingest/clean")

    monkeypatch.setattr(baskets.db, "get_conn", fake_get_conn)
    monkeypatch.setattr(baskets.repo, "load_price_panel", fail)
    with pytest.raises(HTTPException) as exc:
        routes[("/api/baskets/{basket_id}/recompute", "POST")](1, ADMIN)
    assert exc.value.status_code == 404
    assert state.rows[0]["latest_result"] is None


def test_recompute_unknown_basket_404(routes, monkeypatch):
    _bind(monkeypatch, _State([]))
    with pytest.raises(HTTPException) as exc:
        routes[("/api/baskets/{basket_id}/recompute", "POST")](42, ADMIN)
    assert exc.value.status_code == 404


# ---------------------------------------------------------------------------
# 6. DDL 78 幂等
# ---------------------------------------------------------------------------
def test_ddl_78_is_idempotent_and_adds_demo_columns():
    text = (ROOT / "ddl" / "78_basket_demo.sql").read_text(encoding="utf-8")
    assert "BEGIN;" in text and "COMMIT;" in text
    assert re.search(r"ADD COLUMN IF NOT EXISTS is_demo boolean NOT NULL DEFAULT false", text)
    assert re.search(r"ADD COLUMN IF NOT EXISTS display_order integer", text)
    assert "CREATE INDEX IF NOT EXISTS idx_basket_demo_order" in text
    assert "WHERE is_demo = TRUE" in text


# ---------------------------------------------------------------------------
# 7. seed 脚本（定义 + 幂等）
# ---------------------------------------------------------------------------
def _load_seed_module():
    spec = importlib.util.spec_from_file_location(
        "seed_demo_basket", ROOT / "scripts" / "seed_demo_basket.py"
    )
    module = importlib.util.module_from_spec(spec)
    sys.modules["seed_demo_basket"] = module
    spec.loader.exec_module(module)  # type: ignore[union-attr]
    return module


class _SeedFakeCursor:
    def __init__(self, conn: "_SeedFakeConn") -> None:
        self.conn = conn
        self._rows: list = []

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def execute(self, sql: str, params=None) -> None:
        text = " ".join(str(sql).split())
        conn = self.conn
        if "information_schema.columns" in text:
            self._rows = [("is_demo",), ("display_order",)] if conn.has_columns else []
        elif "FROM bp_index_config" in text:
            self._rows = [(symbol,) for symbol in conn.config_symbols]
        elif text.startswith("SELECT basket_id FROM bp_basket"):
            self._rows = [(conn.existing_id,)] if conn.existing_id else []
        elif text.startswith("INSERT INTO bp_basket"):
            conn.next_id += 1
            conn.existing_id = conn.next_id
            self._rows = [(conn.existing_id,)]
        elif text.startswith("UPDATE bp_basket"):
            conn.updates.append(params)
            self._rows = []
        else:
            self._rows = []

    def fetchone(self):
        return self._rows[0] if self._rows else None

    def fetchall(self) -> list:
        return self._rows


class _SeedFakeConn:
    def __init__(self, config_symbols: list[str], has_columns: bool = True) -> None:
        self.config_symbols = config_symbols
        self.has_columns = has_columns
        self.existing_id: int | None = None
        self.next_id = 100
        self.updates: list = []

    def cursor(self):
        return _SeedFakeCursor(self)

    def commit(self) -> None:
        pass


def test_seed_definition_is_12_etl_a_stock_assets_risk_parity():
    module = _load_seed_module()
    definition = module.demo_definition()
    symbols = [item["symbol"] for item in definition["assets"]]
    assert symbols == [
        "600519",
        "300750",
        "600036",
        "601318",
        "000858",
        "000333",
        "600900",
        "601899",
        "002594",
        "600276",
        "601012",
        "603288",
    ]
    assert len(set(symbols)) == 12
    assert all(item["source"] == "etl_a_stock" for item in definition["assets"])
    assert definition["method"] == "risk_parity"
    assert definition["params"] == {
        "lookback_days": 156,
        "rebalance_band": 0.05,
        "risk_free": 0.0,
    }
    assert definition["display_order"] == 0


def test_seed_ensure_is_idempotent():
    module = _load_seed_module()
    symbols = [item["symbol"] for item in module.demo_definition()["assets"]]
    conn = _SeedFakeConn(config_symbols=symbols)
    first = module.ensure_demo_basket(conn)
    second = module.ensure_demo_basket(conn)
    assert first["created"] is True
    assert second == {"basket_id": first["basket_id"], "created": False}
    assert len(conn.updates) == 1


def test_seed_rejects_missing_assets_and_missing_ddl():
    module = _load_seed_module()
    with pytest.raises(RuntimeError, match="bp_index_config"):
        module.ensure_demo_basket(_SeedFakeConn(config_symbols=[]))
    with pytest.raises(RuntimeError, match="ddl/78"):
        module.ensure_demo_basket(_SeedFakeConn(config_symbols=[], has_columns=False))