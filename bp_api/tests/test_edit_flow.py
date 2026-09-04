"""编辑免重算流程测试(不依赖真实 PostgreSQL)。"""
from datetime import date
from types import SimpleNamespace
from unittest.mock import MagicMock

from bp_api.repositories import canonical_params, is_params_stale


def _pdef(**over):
    base = dict(
        name="旧名字", description="",
        method="quadrant_inner_sharpe_outer_rp", ratio="sharpe", lookback_days=156,
        start_date=date(2018, 1, 1), benchmark_key="bond6040",
        max_weight=0.3333333, rebalance_band=0.07,  # 0.07 -> round4 0.07
        risk_free_rate=0.02, fee_rate=0.00015, slippage_rate=0.00015,
        stamp_duty_rate=0.0005,
        assets=[{"symbol": "510300", "source": "etf_em", "quadrant": "recovery",
                 "display_name": "沪深300ETF"}],
        last_run_params=None,
    )
    base.update(over)
    return SimpleNamespace(**base)


def test_canonical_params_rounds_and_sorts():
    p = _pdef(assets=[
        {"symbol": "B", "source": "s", "quadrant": "recovery", "display_name": ""},
        {"symbol": "A", "source": "s", "quadrant": "overheat", "display_name": ""},
    ])
    c = canonical_params(p)
    assert c["max_weight"] == 0.3333
    assert c["start_date"] == "2018-01-01"
    assert c["assets"] == [["A", "s", "overheat"], ["B", "s", "recovery"]]


def test_stale_when_snapshot_missing():
    assert is_params_stale(canonical_params(_pdef()), None) is True


def test_not_stale_when_equal():
    p = _pdef()
    snap = canonical_params(p)
    assert is_params_stale(canonical_params(p), snap) is False


def test_stale_after_band_change():
    p = _pdef()
    snap = canonical_params(p)
    p2 = _pdef(rebalance_band=0.06)
    assert is_params_stale(canonical_params(p2), snap) is True


def test_r4_aligns_with_pg_numeric_round():
    """迁移 39 回填用 PG round(numeric,4) = half-away-from-zero(0.00015→0.0002),
    Python 内建 round 受银行家舍入+浮点表示影响会得到 0.0001;
    _r4 必须与 PG 口径一致, 否则生产存量 done 组合(fee/slippage=0.00015)全部假阳性 stale。"""
    c = canonical_params(_pdef())
    assert c["fee_rate"] == 0.0002
    assert c["slippage_rate"] == 0.0002
    assert c["stamp_duty_rate"] == 0.0005  # 0.0005 不在边界, 两侧一致


def test_not_stale_when_snapshot_assets_pg_collation_order():
    """迁移 39 回填的 assets 按 PG collation 排序('000688' 排在 '0-10Y' 前,
    与 Python 码点排序相反); 快照侧重排后应判定未过期。"""
    p = _pdef(assets=[
        {"symbol": "0-10Y", "source": "bond_csi_treasury", "quadrant": "recovery",
         "display_name": "中债0-10年"},
        {"symbol": "000688", "source": "cn_index_em", "quadrant": "overheat",
         "display_name": "科创50"},
    ])
    current = canonical_params(p)  # 码点序: 0-10Y 在前
    snap = dict(current, assets=[["000688", "cn_index_em", "overheat"],
                                 ["0-10Y", "bond_csi_treasury", "recovery"]])
    assert is_params_stale(current, snap) is False


def test_stale_when_snapshot_assets_content_differs():
    p = _pdef()
    snap = dict(canonical_params(p),
                assets=[["510300", "etf_em", "overheat"]])  # 象限不同
    assert is_params_stale(canonical_params(p), snap) is True


def test_payload_numeric_round4():
    from bp_api.schemas import UpdatePortfolioIn
    p = UpdatePortfolioIn(
        name="x", start_date=date(2018, 1, 1),
        assets=[{"symbol": "A", "source": "s", "quadrant": "recovery"}],
        rebalance_band=0.07000000000000001, max_weight=0.33333333,
        fee_rate=0.00015000000001, slippage_rate=0.00015, stamp_duty_rate=0.0005,
        risk_free_rate=0.02,
    )
    assert p.rebalance_band == 0.07
    assert p.max_weight == 0.3333
    assert p.fee_rate == 0.0002 or p.fee_rate == 0.00015  # round(0.00015000000001,4)=0.0002


def test_schema_round4_same_semantics_as_repo_r4():
    """schemas 取整校验器与 repositories._r4(Decimal HALF_UP, 对齐 PG numeric round)
    必须同口径: 内建 round 是银行家舍入(0.00015→0.0001), 与迁移 39 快照(0.0002)错位
    会造成 diff/stale 假阳性。"""
    from bp_api.repositories import _r4
    from bp_api.schemas import UpdatePortfolioIn
    for v in (0.00015, 0.00015000000001, 0.00025, 0.05, 0.00005, 0.1, 0.07, 0.07000000000000001):
        p = UpdatePortfolioIn(
            name="x", start_date=date(2018, 1, 1),
            assets=[{"symbol": "A", "source": "s", "quadrant": "recovery"}],
            fee_rate=v, risk_free_rate=0.02,
        )
        assert p.fee_rate == _r4(v), v


def test_diff_payload_detects_band_and_name():
    from bp_api.repositories import diff_payload
    p = _pdef()
    snap_like = SimpleNamespace(**{**_pdef().__dict__})  # noqa: F841 (对照快照, 说明不变式)
    # 模拟 payload: 仅 band 与 name 变化
    payload = SimpleNamespace(
        name="新名字", description=p.description if hasattr(p, "description") else "",
        method=p.method, ratio=p.ratio, lookback_days=p.lookback_days,
        start_date=p.start_date, benchmark_key=p.benchmark_key,
        max_weight=p.max_weight, rebalance_band=0.06, risk_free_rate=p.risk_free_rate,
        fee_rate=p.fee_rate, slippage_rate=p.slippage_rate, stamp_duty_rate=p.stamp_duty_rate,
        assets=[SimpleNamespace(symbol=a["symbol"], source=a["source"], quadrant=a["quadrant"])
                for a in p.assets],
    )
    p.name = "旧名字"
    p.description = ""
    changed = diff_payload(p, payload)
    assert changed == {"name", "rebalance_band"}


def test_diff_payload_no_change_when_identical():
    from bp_api.repositories import diff_payload
    p = _pdef()
    payload = SimpleNamespace(
        name=p.name, description=p.description,
        method=p.method, ratio=p.ratio, lookback_days=p.lookback_days,
        start_date=p.start_date, benchmark_key=p.benchmark_key,
        max_weight=p.max_weight, rebalance_band=p.rebalance_band,
        risk_free_rate=p.risk_free_rate,
        fee_rate=p.fee_rate, slippage_rate=p.slippage_rate, stamp_duty_rate=p.stamp_duty_rate,
        assets=[SimpleNamespace(symbol=a["symbol"], source=a["source"], quadrant=a["quadrant"])
                for a in p.assets],
    )
    assert diff_payload(p, payload) == set()


def test_diff_payload_epsilon_band_not_flagged():
    """浮点 epsilon 级 band 差(0.07000000000000001 vs 0.07)不算变化——
    schema round4 归一后 diff 不产生假阳性(前端 toFixed 误差防御)。"""
    from bp_api.repositories import diff_payload
    p = _pdef()
    payload = SimpleNamespace(
        name=p.name, description=p.description,
        method=p.method, ratio=p.ratio, lookback_days=p.lookback_days,
        start_date=p.start_date, benchmark_key=p.benchmark_key,
        max_weight=p.max_weight, rebalance_band=0.07000000000000001,
        risk_free_rate=p.risk_free_rate,
        fee_rate=p.fee_rate, slippage_rate=p.slippage_rate, stamp_duty_rate=p.stamp_duty_rate,
        assets=[SimpleNamespace(symbol=a["symbol"], source=a["source"], quadrant=a["quadrant"])
                for a in p.assets],
    )
    assert diff_payload(p, payload) == set()


def test_update_portfolio_def_only_columns_and_assets():
    """UPDATE 列集与 update_portfolio 对齐(无 status; updated_by 走 COALESCE 审计), 资产先删后插。"""
    from bp_api.repositories import update_portfolio_def_only

    cur = MagicMock()
    conn = MagicMock()
    conn.cursor.return_value.__enter__ = MagicMock(return_value=cur)
    conn.cursor.return_value.__exit__ = MagicMock(return_value=False)

    a1 = SimpleNamespace(symbol="510300", source="etf_em", quadrant="recovery", display_name="沪深300ETF")
    a2 = SimpleNamespace(symbol="0-10Y", source="bond_csi_treasury", quadrant="recession", display_name=None)
    payload = SimpleNamespace(
        name="n", description="d", method="m", ratio="sharpe", lookback_days=156,
        start_date=date(2018, 1, 1), benchmark_key="bond6040",
        max_weight=0.3333, rebalance_band=0.07, risk_free_rate=0.02,
        fee_rate=0.00015, slippage_rate=0.00015, stamp_duty_rate=0.0005,
        assets=[a1, a2],
    )
    update_portfolio_def_only(conn, 7, payload, updater_user_id=42)
    calls = cur.execute.call_args_list
    update_sql, update_params = calls[0][0]
    assert "SET name=" in update_sql
    for col in ["name", "description", "method", "ratio", "lookback_days", "start_date",
                "benchmark_key", "max_weight", "rebalance_band", "risk_free_rate",
                "fee_rate", "slippage_rate", "stamp_duty_rate",
                "updated_by", "updated_at"]:
        assert col in update_sql
    assert "status" not in update_sql
    # 审计口径与 update_portfolio 一致: 有 user_id 时写入, 缺省 COALESCE 保留原值
    assert "updated_by=COALESCE(%s, updated_by)" in update_sql
    assert update_params[-2] == 42  # updated_by 占位参数
    # 13 个定义列 + updated_by + WHERE portfolio_id = 15; updated_at 由 SQL now() 生成
    assert update_sql.count("%s") == len(update_params) == 15
    assert update_params[-1] == 7  # WHERE portfolio_id
    delete_sql, delete_params = calls[1][0]
    assert delete_sql.startswith("DELETE FROM bp_portfolio_asset")
    assert delete_params == (7,)
    insert_sql, insert_params = calls[2][0]
    assert "INSERT INTO bp_portfolio_asset" in insert_sql
    assert insert_params == (7, "510300", "etf_em", "recovery", "沪深300ETF", 0)
    assert calls[3][0][1] == (7, "0-10Y", "bond_csi_treasury", "recession", None, 1)


def test_update_portfolio_def_only_user_id_none_keeps_updated_by():
    """updater_user_id=None 时 COALESCE 保留库中原 updated_by(占位传 None, 非 SQL NULL 直写)。"""
    from bp_api.repositories import update_portfolio_def_only

    cur = MagicMock()
    conn = MagicMock()
    conn.cursor.return_value.__enter__ = MagicMock(return_value=cur)
    conn.cursor.return_value.__exit__ = MagicMock(return_value=False)
    payload = SimpleNamespace(
        name="n", description="d", method="m", ratio="sharpe", lookback_days=156,
        start_date=date(2018, 1, 1), benchmark_key="bond6040",
        max_weight=0.3333, rebalance_band=0.07, risk_free_rate=0.02,
        fee_rate=0.00015, slippage_rate=0.00015, stamp_duty_rate=0.0005,
        assets=[SimpleNamespace(symbol="A", source="s", quadrant="recovery", display_name=None)],
    )
    update_portfolio_def_only(conn, 7, payload)
    update_sql, update_params = cur.execute.call_args_list[0][0]
    assert "updated_by=COALESCE(%s, updated_by)" in update_sql
    assert update_params[-2] is None


def test_is_portfolio_stale_via_mock():
    """is_portfolio_stale 走 read_def → canonical_params → is_params_stale 链路。"""
    from bp_api import repositories as repo

    pdef = _pdef(last_run_params=canonical_params(_pdef()))
    rows = [(
        1, pdef.name, pdef.description, pdef.method, pdef.ratio, pdef.lookback_days,
        pdef.start_date, pdef.benchmark_key, pdef.max_weight, pdef.rebalance_band,
        False, None, pdef.risk_free_rate, pdef.fee_rate, pdef.slippage_rate,
        pdef.stamp_duty_rate, 1, None, pdef.last_run_params,
    )]
    asset_rows = [(a["symbol"], a["source"], a["quadrant"], a["display_name"]) for a in pdef.assets]

    class _Cur:
        def __enter__(self):
            return self
        def __exit__(self, *a):
            return False
        def execute(self, sql, params):
            self._last = sql
        def fetchone(self):
            if "bp_portfolio_asset" in self._last:
                raise AssertionError("asset 查询不该走 fetchone")
            return rows.pop(0) if rows else (asset_rows and None)
        def fetchall(self):
            return asset_rows

    class _Conn:
        def cursor(self):
            return _Cur()

    # 快照=当前参数 → 未过期
    assert repo.is_portfolio_stale(_Conn(), 1) is False
    # 从未回测 → 过期
    pdef2 = _pdef(last_run_params=None)
    rows.append((
        1, pdef2.name, pdef2.description, pdef2.method, pdef2.ratio, pdef2.lookback_days,
        pdef2.start_date, pdef2.benchmark_key, pdef2.max_weight, pdef2.rebalance_band,
        False, None, pdef2.risk_free_rate, pdef2.fee_rate, pdef2.slippage_rate,
        pdef2.stamp_duty_rate, 1, None, pdef2.last_run_params,
    ))
    assert repo.is_portfolio_stale(_Conn(), 1) is True


def test_list_recomputable_portfolio_ids():
    """Task 7: 取非 running 且有资产的组合 id, 按 id 升序。"""
    from bp_api.repositories import list_recomputable_portfolio_ids
    conn = MagicMock()
    cur = MagicMock()
    conn.cursor.return_value.__enter__ = MagicMock(return_value=cur)
    conn.cursor.return_value.__exit__ = MagicMock(return_value=False)
    cur.fetchall.return_value = [(1,), (4,), (7,)]
    assert list_recomputable_portfolio_ids(conn) == [1, 4, 7]


def test_list_recomputable_portfolio_ids_sql_semantics():
    """SQL 须同时含三要素: status <> 'running'、资产 EXISTS、ORDER BY portfolio_id。"""
    from bp_api.repositories import list_recomputable_portfolio_ids

    cur = MagicMock()
    conn = MagicMock()
    conn.cursor.return_value.__enter__ = MagicMock(return_value=cur)
    conn.cursor.return_value.__exit__ = MagicMock(return_value=False)
    cur.fetchall.return_value = [(1,)]
    list_recomputable_portfolio_ids(conn)
    sql = " ".join(cur.execute.call_args[0][0].split())
    assert "status <> 'running'" in sql
    assert "EXISTS (SELECT 1 FROM bp_portfolio_asset" in sql
    assert "ORDER BY p.portfolio_id" in sql


# ---------------------------------------------------------------------
# Task 7: PATCH /api/portfolios/{id}/meta handler 级分支测试(无真实 DB)
# ---------------------------------------------------------------------
def _fake_user(user_id=42, is_admin=True):
    from bp_api.auth import UserContext

    return UserContext(user_id=user_id, email="u@b.c", role="admin",
                       is_admin=is_admin, can_manage_assets=True)


class _MetaConn:
    """记录 execute/commit 的伪造连接, 供断言「落了什么、没动什么」。"""

    def __init__(self):
        self.executed: list[tuple[str, tuple | None]] = []
        self.commits = 0
        self.rollbacks = 0
        self._cur = _MetaCur(self)

    def cursor(self):
        return self._cur

    def commit(self):
        self.commits += 1

    def rollback(self):
        self.rollbacks += 1


class _MetaCur:
    def __init__(self, conn):
        self._conn = conn
        self.fetchone_result = None
        self.fetchall_result: list = []

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False

    def execute(self, sql, params=None):
        self._conn.executed.append((" ".join(sql.split()), params))

    def fetchone(self):
        return self.fetchone_result

    def fetchall(self):
        return self.fetchall_result


def _ctx(conn):
    from contextlib import contextmanager

    @contextmanager
    def _get_conn():
        yield conn

    return _get_conn()


def _meta_payload(**over):
    """构造合法 UpdatePortfolioIn。max_weight=1 单资产才能过 _validate_portfolio_payload
    (品种数×上限≥100%); 数值与 _pdef() 对齐使 diff 仅含 name。"""
    from bp_api.schemas import UpdatePortfolioIn

    base = dict(
        name="新名字", description="",
        method="quadrant_inner_sharpe_outer_rp", ratio="sharpe", lookback_days=156,
        start_date=date(2018, 1, 1), benchmark_key="bond6040",
        max_weight=1.0, rebalance_band=0.07, risk_free_rate=0.02,
        fee_rate=0.00015, slippage_rate=0.00015, stamp_duty_rate=0.0005,
        assets=[{"symbol": "510300", "source": "etf_em", "quadrant": "recovery"}],
    )
    base.update(over)
    return UpdatePortfolioIn(**base)


def _patch_meta_deps(monkeypatch, *, status=None, pdef=None, stale=False):
    """伪造 db.get_conn 与 repo 查询函数; diff_payload/update_portfolio_def_only 走真实实现。

    status=None 表示组合不存在(get_portfolio_status 抛 KeyError)。返回 (conn, dispatch_calls)。"""
    from bp_api import main

    conn = _MetaConn()
    monkeypatch.setattr(main.db, "get_conn", lambda: _ctx(conn))

    def _status(c, pid):
        if status is None:
            raise KeyError(f"组合不存在: {pid}")
        return {"portfolio_id": pid, "status": status, "error": None,
                "effective_start_date": None}

    monkeypatch.setattr(main.repo, "get_portfolio_status", _status)
    monkeypatch.setattr(main.repo, "can_edit_portfolio", lambda c, pid, uid, adm: True)
    monkeypatch.setattr(main.repo, "read_def", lambda c, pid: pdef)
    monkeypatch.setattr(main.repo, "is_portfolio_stale", lambda c, pid: stale)
    monkeypatch.setattr(main.cache, "delete_pattern", lambda pat: None)
    dispatch_calls: list = []
    monkeypatch.setattr(main, "_dispatch_backtest",
                        lambda *a, **k: dispatch_calls.append(a))
    return conn, dispatch_calls


def test_meta_running_with_backtest_fields_409(monkeypatch):
    """① running + 回测字段变化 → 409, 不落定义、不 commit、不派发。"""
    import pytest
    from fastapi import HTTPException

    from bp_api import main

    pdef = _pdef(max_weight=1.0)
    conn, dispatch_calls = _patch_meta_deps(monkeypatch, status="running", pdef=pdef)
    payload = _meta_payload(lookback_days=200)  # 回测字段变化
    with pytest.raises(HTTPException) as ei:
        main.update_portfolio_meta(7, payload, user=_fake_user())
    assert ei.value.status_code == 409
    assert conn.executed == []  # 409 前不落任何 SQL
    assert conn.commits == 0
    assert dispatch_calls == []


def test_meta_running_rename_only_200_no_dispatch(monkeypatch):
    """② running + 仅改名 → 200: 落定义+commit, 但无 status 变更、无 bp_task 写入、不派发。"""
    from bp_api import main

    pdef = _pdef(max_weight=1.0)
    conn, dispatch_calls = _patch_meta_deps(monkeypatch, status="running", pdef=pdef)
    payload = _meta_payload(name="全新名字")  # 仅 name 与 pdef 不同
    out = main.update_portfolio_meta(7, payload, user=_fake_user())
    assert out == {"portfolio_id": 7, "params_stale": False}
    assert conn.commits == 1
    # 落了定义(免重算全字段保存), 但不动 status、不建任务
    assert any("UPDATE bp_portfolio" in sql for sql, _ in conn.executed)
    assert not any("status='running'" in sql or "SET status" in sql for sql, _ in conn.executed)
    assert not any("bp_task" in sql for sql, _ in conn.executed)
    assert dispatch_calls == []


def test_meta_portfolio_not_found_404(monkeypatch):
    """③ 组合不存在 → 404(get_portfolio_status 抛 KeyError), 不落任何 SQL。"""
    import pytest
    from fastapi import HTTPException

    from bp_api import main

    conn, dispatch_calls = _patch_meta_deps(monkeypatch, status=None)
    with pytest.raises(HTTPException) as ei:
        main.update_portfolio_meta(99, _meta_payload(), user=_fake_user())
    assert ei.value.status_code == 404
    assert conn.executed == []
    assert conn.commits == 0


def test_meta_blank_name_400(monkeypatch):
    """④ 空白名 → 400(过 409 门后兜底校验), 不落定义。"""
    import pytest
    from fastapi import HTTPException

    from bp_api import main

    pdef = _pdef(max_weight=1.0)
    conn, dispatch_calls = _patch_meta_deps(monkeypatch, status="running", pdef=pdef)
    with pytest.raises(HTTPException) as ei:
        main.update_portfolio_meta(7, _meta_payload(name="  "), user=_fake_user())
    assert ei.value.status_code == 400
    assert conn.commits == 0
    assert dispatch_calls == []


# ---------------------------------------------------------------------
# Task 7: recompute-all 端点 handler 级测试(无真实 DB)
# ---------------------------------------------------------------------
def test_recompute_all_enqueues_each_in_order(monkeypatch):
    """循环体与单组合 recompute 端点入队语义一致:
    每组合依次 _enqueue_backtest(幂等, 置 running) + commit; 全部 commit 后才统一派发;
    task_type 走 'backtest'(ck_bp_task_type 无 'recompute_all')。"""
    from bp_api import main

    conn = _MetaConn()
    pids = [1, 4, 7]
    monkeypatch.setattr(main.db, "get_conn", lambda: _ctx(conn))
    monkeypatch.setattr(main.repo, "list_recomputable_portfolio_ids", lambda c: list(pids))

    created: list[tuple[str, int, str]] = []

    def _fake_create_task(c, task_type, portfolio_id=None, owner_user_id=None,
                          progress_total=1, message=""):
        tid = f"task-{portfolio_id}"
        created.append((task_type, portfolio_id, tid))
        return tid

    monkeypatch.setattr(main.tasking, "create_task", _fake_create_task)
    monkeypatch.setattr(main.tasking, "find_active_portfolio_task", lambda c, pid: None)

    dispatch_calls: list = []
    monkeypatch.setattr(main, "_dispatch_backtest",
                        lambda *a, **k: dispatch_calls.append(a))

    from fastapi import BackgroundTasks

    out = main.recompute_all_portfolios(
        background_tasks=BackgroundTasks(),
        user=_fake_user(user_id=42, is_admin=True),
    )
    assert out == {"enqueued": 3}
    # 入队顺序 = id 升序, task_type='backtest'
    assert created == [("backtest", 1, "task-1"), ("backtest", 4, "task-4"),
                       ("backtest", 7, "task-7")]
    # 每组合一次 commit(事务提交后才可见), 且全部提交完才统一派发
    assert conn.commits == 3
    assert [(t, p) for t, p, _bg in dispatch_calls] == [
        ("task-1", 1), ("task-4", 4), ("task-7", 7)]
    # _enqueue_backtest 内部: UPDATE status='running' (INSERT 由 mock 的 create_task 吸收)
    assert sum(1 for sql, _ in conn.executed if "status='running'" in sql) == 3


def test_recompute_all_skips_when_active_task_exists(monkeypatch):
    """_enqueue_backtest 幂等: 已有活动任务时复用 task_id, 不再 INSERT 新任务。"""
    from bp_api import main
    from fastapi import BackgroundTasks

    conn = _MetaConn()
    monkeypatch.setattr(main.db, "get_conn", lambda: _ctx(conn))
    monkeypatch.setattr(main.repo, "list_recomputable_portfolio_ids", lambda c: [5])
    monkeypatch.setattr(main.tasking, "find_active_portfolio_task",
                        lambda c, pid: "existing-task")
    dispatch_calls: list = []
    monkeypatch.setattr(main, "_dispatch_backtest",
                        lambda *a, **k: dispatch_calls.append(a))

    out = main.recompute_all_portfolios(
        background_tasks=BackgroundTasks(),
        user=_fake_user(),
    )
    assert out == {"enqueued": 1}
    # 复用已有任务: 无 INSERT, 无 status 置 running(原任务已在跑), 但仍派发
    assert not any("INSERT INTO bp_task" in sql for sql, _ in conn.executed)
    assert [(t, p) for t, p, _bg in dispatch_calls] == [("existing-task", 5)]


def test_recompute_all_continues_on_single_failure(monkeypatch):
    """单组合入队失败: 记日志 + rollback 跳过, 不阻断其余组合; enqueued 只数成功者。"""
    from bp_api import main
    from fastapi import BackgroundTasks

    conn = _MetaConn()
    monkeypatch.setattr(main.db, "get_conn", lambda: _ctx(conn))
    monkeypatch.setattr(main.repo, "list_recomputable_portfolio_ids", lambda c: [1, 2, 3])

    def _create(c, task_type, portfolio_id=None, owner_user_id=None,
                progress_total=1, message=""):
        if portfolio_id == 2:
            raise RuntimeError("boom")
        return f"task-{portfolio_id}"

    monkeypatch.setattr(main.tasking, "create_task", _create)
    monkeypatch.setattr(main.tasking, "find_active_portfolio_task", lambda c, pid: None)
    dispatch_calls: list = []
    monkeypatch.setattr(main, "_dispatch_backtest",
                        lambda *a, **k: dispatch_calls.append(a))

    out = main.recompute_all_portfolios(
        background_tasks=BackgroundTasks(),
        user=_fake_user(),
    )
    assert out == {"enqueued": 2}
    assert conn.rollbacks == 1
    assert [(t, p) for t, p, _bg in dispatch_calls] == [("task-1", 1), ("task-3", 3)]


def test_recompute_all_requires_super_admin_semantics(monkeypatch):
    """require_super_admin 对非 admin UserContext 抛 403: 直接驱动依赖内部逻辑
    (require_user 部分 monkeypatch 掉, 无真实 DB)。"""
    import pytest
    from fastapi import HTTPException

    from bp_api import auth

    non_admin = _fake_user(user_id=42, is_admin=False)
    monkeypatch.setattr(auth, "require_user", lambda authorization: non_admin)
    with pytest.raises(HTTPException) as ei:
        auth.require_super_admin(authorization="Bearer x")
    assert ei.value.status_code == 403

    admin = _fake_user(user_id=1, is_admin=True)
    monkeypatch.setattr(auth, "require_user", lambda authorization: admin)
    assert auth.require_super_admin(authorization="Bearer x") is admin


def test_create_user_in_accepts_unlimited():
    from bp_api.schemas import CreateUserIn
    body = CreateUserIn(email="a@b.c", password="pw123456", portfolio_limit=None,
                        can_manage_assets=True)
    assert body.portfolio_limit is None
    assert body.can_manage_assets is True
    assert CreateUserIn(email="a@b.c", password="x").portfolio_limit == 3
    import pytest
    from pydantic import ValidationError
    with pytest.raises(ValidationError):
        CreateUserIn(email="a@b.c", password="x", portfolio_limit=-1)


def test_get_user_portfolio_limit_null_means_unlimited():
    from bp_api.repositories import get_user_portfolio_limit
    cur = MagicMock()
    conn = MagicMock()
    conn.cursor.return_value.__enter__ = MagicMock(return_value=cur)
    conn.cursor.return_value.__exit__ = MagicMock(return_value=False)
    cur.fetchone.return_value = ("user", None)
    assert get_user_portfolio_limit(conn, 1) is None
    cur.fetchone.return_value = ("user", 5)
    assert get_user_portfolio_limit(conn, 1) == 5
    cur.fetchone.return_value = ("admin", 3)
    assert get_user_portfolio_limit(conn, 1) is None


def test_update_user_three_state_portfolio_limit(monkeypatch):
    """「未传不改 / 传 null 清为 NULL / 传数值更新」三态: 哨兵 _UNSET 区分未传与显式 None。"""
    import pytest as _pytest
    from fastapi import HTTPException
    from bp_api import auth

    class _Cur:
        def __init__(self):
            self.executed: list[tuple[str, tuple | None]] = []
            self._result = (5,)
            self._updated = None

        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

        def execute(self, sql, params=None):
            self.executed.append((sql, params))
            normalized = " ".join(sql.split())
            if normalized.startswith("SELECT to_regclass"):
                self._result = ("bp_user",)
            elif "RETURNING portfolio_limit" in normalized:
                self._result = self._updated
            elif normalized.startswith("SELECT portfolio_limit"):
                self._result = (5,)

        def fetchone(self):
            return self._result

    class _Conn:
        def __init__(self):
            self._cur = _Cur()
            self.committed = False

        def cursor(self):
            return self._cur

        def commit(self):
            self.committed = True

    from contextlib import contextmanager

    @contextmanager
    def get_conn():
        yield conn_obj

    # 未传: 抛 400(无可更新字段), 不执行任何 UPDATE
    conn_obj = _Conn()
    monkeypatch.setattr(auth.db, "get_conn", get_conn)
    with _pytest.raises(HTTPException) as ei:
        auth.update_user("u@b.c")
    assert ei.value.status_code == 400
    assert not any("UPDATE bp_user" in sql for sql, _ in conn_obj._cur.executed)

    # 显式 None: 写入 NULL(SET portfolio_limit=NULL)
    conn_obj = _Conn()
    monkeypatch.setattr(auth.db, "get_conn", get_conn)
    conn_obj._cur._updated = (None,)
    out = auth.update_user("u@b.c", portfolio_limit=None)
    set_null = [p for sql, p in conn_obj._cur.executed
                if "SET portfolio_limit=%s" in " ".join(sql.split())]
    assert set_null == [(None, "u@b.c")], "显式 null 须写入 SQL NULL"
    assert out["portfolio_limit"] is None

    # 传数值: 正常更新
    conn_obj = _Conn()
    monkeypatch.setattr(auth.db, "get_conn", get_conn)
    conn_obj._cur._updated = (7,)
    out = auth.update_user("u@b.c", portfolio_limit=7)
    set_num = [p for sql, p in conn_obj._cur.executed
               if "SET portfolio_limit=%s" in " ".join(sql.split())]
    assert set_num == [(7, "u@b.c")]
    assert out["portfolio_limit"] == 7


def test_update_user_rejects_negative_limit(monkeypatch):
    from fastapi import HTTPException
    from bp_api import auth

    class _Cur:
        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

        def execute(self, sql, params=None):
            if sql.startswith("SELECT to_regclass"):
                self._result = ("bp_user",)
            elif sql.strip().startswith("SELECT portfolio_limit"):
                self._result = (5,)

        def fetchone(self):
            return self._result

    class _Conn:
        def cursor(self):
            return _Cur()

        def commit(self):
            pass

    from contextlib import contextmanager

    @contextmanager
    def get_conn():
        yield _Conn()

    monkeypatch.setattr(auth.db, "get_conn", get_conn)
    try:
        auth.update_user("u@b.c", portfolio_limit=-1)
        raised = False
    except HTTPException as e:
        raised = e.status_code == 400
    assert raised, "负数上限应拒绝"


def test_create_user_passes_new_columns(monkeypatch):
    """create_user 透传 portfolio_limit/can_manage_assets 两列到 INSERT。"""
    from bp_api import auth

    class _Cur:
        def __init__(self):
            self.executed: list[tuple[str, tuple | None]] = []

        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

        def execute(self, sql, params=None):
            self.executed.append((sql, params))
            if sql.startswith("SELECT to_regclass"):
                self._result = ("bp_user",)

        def fetchone(self):
            return self._result

    class _Conn:
        def __init__(self):
            self._cur = _Cur()
            self.committed = False

        def cursor(self):
            return self._cur

        def commit(self):
            self.committed = True

    from contextlib import contextmanager

    @contextmanager
    def get_conn():
        yield conn_obj

    conn_obj = _Conn()
    monkeypatch.setattr(auth.db, "get_conn", get_conn)
    monkeypatch.setattr(auth, "user_exists", lambda email: False)
    monkeypatch.setattr(auth, "hash_password", lambda pw: "hashed")

    auth.create_user("u@b.c", "pw123456", portfolio_limit=None, can_manage_assets=True)
    bp_inserts = [p for sql, p in conn_obj._cur.executed if "INSERT INTO bp_user" in sql]
    assert bp_inserts, "须写入 bp_user"
    params = bp_inserts[0]
    # (email, hash, portfolio_limit, can_manage_assets) 且 SQL 显式列名
    sql = next(sql for sql, _ in conn_obj._cur.executed if "INSERT INTO bp_user" in sql)
    assert "portfolio_limit" in sql and "can_manage_assets" in sql
    assert params == ("u@b.c", "hashed", None, True)
    # legacy bp_admin_user 写入保持
    assert any("INSERT INTO bp_admin_user" in sql for sql, _ in conn_obj._cur.executed)
