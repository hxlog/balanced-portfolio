"""API 路由注册 smoke tests。"""

from bp_api.main import app


def _route_methods(path: str) -> set[str]:
    methods: set[str] = set()
    for route in app.routes:
        if getattr(route, "path", None) == path and hasattr(route, "methods"):
            methods |= set(route.methods or [])
    return methods


def test_put_portfolio_route_registered():
    methods = _route_methods("/api/portfolios/{portfolio_id}")
    assert "PUT" in methods
    assert "GET" in methods
    assert "DELETE" in methods


def test_demo_route_registered():
    assert "GET" in _route_methods("/api/portfolios/demo")
    assert "PATCH" in _route_methods("/api/portfolios/{portfolio_id}/demo")


def test_admin_user_routes_registered():
    assert "GET" in _route_methods("/api/admin/users")
    assert "POST" in _route_methods("/api/admin/users")
    assert "DELETE" in _route_methods("/api/admin/users/{email}")


def test_portfolio_meta_route_accepts_full_payload():
    """Task 5: PATCH /meta 扩展为免重算全字段保存, 请求模型须为 UpdatePortfolioIn。"""
    import inspect

    from bp_api.main import update_portfolio_meta

    sig = inspect.signature(update_portfolio_meta)
    assert "payload" in sig.parameters
    ann = sig.parameters["payload"].annotation
    ann_name = getattr(ann, "__name__", None) or str(ann)
    assert "UpdatePortfolioIn" in ann_name


def test_recompute_all_route_registered():
    """Task 7: POST /api/admin/portfolios/recompute-all, 必须挂超管依赖。"""
    import inspect

    from bp_api import auth, main

    assert "POST" in _route_methods("/api/admin/portfolios/recompute-all")
    sig = inspect.signature(main.recompute_all_portfolios)
    dep = sig.parameters["user"].default
    assert getattr(dep, "dependency", None) is auth.require_super_admin


def test_probe_admin_asset_route_accepts_optional_extra_body():
    """Task 3: probe 端点接受可选 JSON body AssetProbeIn(extra_params), 缺省 {} 向后兼容。"""
    import inspect

    from bp_api.main import probe_admin_asset

    assert "POST" in _route_methods("/api/admin/assets/{source}/{symbol}/probe")
    sig = inspect.signature(probe_admin_asset)
    param = sig.parameters["payload"]
    assert param.default is None  # body 可缺省
    assert "AssetProbeIn" in str(param.annotation)


def test_asset_portfolio_refs_route_registered():
    """资产反查组合端点: 必须存在, 且挂 require_asset_editor(与资产管理同权限口径)。

    需求 16 的删除/停用前提示依赖它 —— 路由缺失时前端只会拿到 404, 静默降级成
    「无组合引用」, 让用户以为删掉某资产不影响任何组合。
    """
    import inspect

    from bp_api import auth, main

    assert "GET" in _route_methods("/api/admin/assets/portfolio-refs")
    sig = inspect.signature(main.list_asset_portfolio_refs)
    dep = sig.parameters["_"].default
    assert getattr(dep, "dependency", None) is auth.require_asset_editor


def test_asset_portfolio_refs_repository_shape():
    """反查仓库返回 [{key: 'symbol@source', portfolios: [...]}], 前端按 key 查表。"""
    from unittest.mock import MagicMock

    from bp_api.repositories import list_asset_portfolios

    conn = MagicMock()
    cur = conn.cursor.return_value.__enter__.return_value
    # SELECT DISTINCT a.symbol, a.source, p.portfolio_id, p.name, p.is_demo
    cur.fetchall.return_value = [
        ("HSTECH", "hk_index_em", 24, "我的组合", False),
        ("HSTECH", "hk_index_em", 31, "港股组合", False),
        ("标普500", "global_index_em", 28, "最简单版本 (Demo)", True),
    ]
    out = list_asset_portfolios(conn)

    by_key = {r["key"]: r["portfolios"] for r in out}
    assert by_key["HSTECH@hk_index_em"] == [
        {"portfolio_id": 24, "name": "我的组合", "is_demo": False},
        {"portfolio_id": 31, "name": "港股组合", "is_demo": False},
    ]
    assert by_key["标普500@global_index_em"] == [
        {"portfolio_id": 28, "name": "最简单版本 (Demo)", "is_demo": True}
    ]
    # 同一资产在组合里多行(不同象限)只应出现一次 —— SQL 侧已 DISTINCT, 这里固化返回形状
    assert len(by_key) == 2
